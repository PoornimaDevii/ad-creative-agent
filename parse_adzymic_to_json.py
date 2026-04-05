"""
Parse adzymic_raw.html -> creative_formats.json (AdCP schema)

Run:  python parse_adzymic_to_json.py
Output: creative_formats.json  (overwrites existing file)
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def extract_numbers(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", text)]


def first_number(text: str) -> int | None:
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def parse_sizes(text: str) -> list[dict]:
    """Turn '300x250 300x600 970x250' into [{"width":300,"height":250}, ...]"""
    sizes = []
    for m in re.finditer(r"(\d{2,4})\s*[xX×]\s*(\d{2,4})", text):
        sizes.append({"width": int(m.group(1)), "height": int(m.group(2))})
    return sizes


def infer_type(name: str) -> str:
    """Infer AdCP format type from name. Valid values: audio, video, display, dooh."""
    n = name.lower()
    if any(x in n for x in ["video", "vertical video", "horizontal video", "in-banner"]):
        return "video"
    if "audio" in n:
        return "audio"
    if "dooh" in n or "out-of-home" in n:
        return "dooh"
    # All other formats including social display ads are display type
    return "display"


def infer_asset_type(name: str) -> list[str]:
    n = name.lower()
    types = ["image"]
    if any(x in n for x in ["video", "in-banner", "hotspot"]):
        types = ["video", "image"]
    if "chatbot" in n:
        types = ["text", "image"]
    if "lead gen" in n:
        types = ["image", "text"]
    return types


def make_format_id(name: str, idx: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"adzymic-{slug}-{idx:03d}"


# ---------------------------------------------------------------------------
# Table parser — extracts all spec fields from a format's <table>
# ---------------------------------------------------------------------------

def parse_spec_table(table) -> dict:
    spec = {
        "available_sizes": [],
        "text_limits": {},
        "text_limit_variants": [],  # all ad copy variants e.g. title only, title+desc etc
        "min_cards": None,
        "min_cards_by_size": {},    # e.g. {"300x250": 3, "300x600": 4}
        "image_dimensions": [],
        "feature_image_dimensions": None,
        "video_requirements": None,
        "dco_available": False,
        "additional_requirements": [],
        "optional_requirements": [],
        "ad_fields": {},
        "notes": [],
    }

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        key = clean_text(cells[0]).lower()
        val = clean_text(cells[1])

        # Available sizes
        if re.search(r"available\s+size", key):
            spec["available_sizes"] = parse_sizes(val)

        # Text limit variants — rows like "Ad with Title Only", "Ad with Title and Description"
        elif re.search(r"ad\s+with\s+title", key) or re.search(r"ad\s+fields", key):
            variant = {"label": clean_text(cells[0])}
            _parse_text_limits(val, variant)
            spec["text_limit_variants"].append(variant)
            # Prefer the most complete variant (title+button+description has all fields)
            # Update only if this variant has more fields than what we have so far
            variant_fields = {k: v for k, v in variant.items() if k != "label"}
            current_fields = {k: v for k, v in spec["text_limits"].items()}
            if len(variant_fields) > len(current_fields):
                spec["text_limits"].update(variant_fields)

        # Plain Title / Description / CTA rows
        elif re.match(r"^title$", key):
            n = first_number(val)
            if n:
                spec["text_limits"]["title"] = n

        elif re.match(r"^description$", key):
            n = first_number(val)
            if n:
                spec["text_limits"]["description"] = n

        elif re.match(r"^cta\s+button$", key):
            n = first_number(val)
            if n:
                spec["text_limits"]["button"] = n

        # Min cards — parse per-size breakdown
        elif re.search(r"minimum\s+cards|number\s+of\s+cards|cards\s+required", key):
            nums = extract_numbers(val)
            if nums:
                spec["min_cards"] = min(nums)
            # Parse per-size breakdown e.g. "300x250: 3 cards 300x600: 4 cards"
            for m in re.finditer(r"(\d{2,4}x\d{2,4})\s*:\s*(\d+)", val):
                spec["min_cards_by_size"][m.group(1)] = int(m.group(2))

        # Image / card dimensions
        elif re.search(r"dimension\s+of\s+(images|cards|tile)", key):
            spec["image_dimensions"].append(val)

        # Feature image dimensions
        elif re.search(r"dimension\s+of\s+feature", key):
            spec["feature_image_dimensions"] = val

        # Video requirements
        elif re.search(r"video\s+required|youtube\s+video", key):
            spec["video_requirements"] = val

        # DCO
        elif re.search(r"product\s+dco", key):
            spec["dco_available"] = "yes" in val.lower()

        # Additional requirements
        elif re.search(r"additional", key) and "optional" not in key:
            # Split additional vs optional
            additional_match = re.search(r"additional[:\s]+(.*?)(?:optional[:\s]|$)", val, re.IGNORECASE | re.DOTALL)
            optional_match = re.search(r"optional[:\s]+(.*?)$", val, re.IGNORECASE | re.DOTALL)
            if additional_match:
                spec["additional_requirements"] = [
                    line.strip().lstrip("- ") for line in additional_match.group(1).strip().splitlines()
                    if line.strip() and line.strip() != "-"
                ]
            if optional_match:
                spec["optional_requirements"] = [
                    line.strip().lstrip("- ") for line in optional_match.group(1).strip().splitlines()
                    if line.strip() and line.strip() != "-"
                ]

    return spec


def _parse_text_limits(val: str, limits: dict):
    """Extract title/description/button limits from a value string."""
    for field, pattern in [
        ("title",       r"title[:\s]+(\d+)"),
        ("description", r"description[:\s]+(\d+)"),
        ("button",      r"button[:\s]+(\d+)"),
        ("footer",      r"footer[:\s]+(\d+)"),
        ("form_title",  r"form\s+title[:\s]+(\d+)"),
    ]:
        m = re.search(pattern, val, re.IGNORECASE)
        if m:
            limits[field] = int(m.group(1))


# ---------------------------------------------------------------------------
# Build AdCP-schema assets[] from parsed spec
# ---------------------------------------------------------------------------

def build_assets(name: str, spec: dict) -> list[dict]:
    assets = []
    tl = spec["text_limits"]
    asset_types = infer_asset_type(name)

    # Image asset
    if "image" in asset_types:
        img_req: dict = {}
        if spec["min_cards"]:
            img_req["min"] = spec["min_cards"]
        # Extract clean aspect ratio from image dimensions e.g. "2:1" from "1040 x 520 px or 2:1 Aspect Ratio"
        if spec["image_dimensions"]:
            ratio_match = re.search(r"(\d+:\d+(?:\.\d+)?)", spec["image_dimensions"][0])
            if ratio_match:
                img_req["aspect_ratio"] = ratio_match.group(1)
            # Extract pixel dimensions e.g. "1040 x 520"
            px_match = re.search(r"(\d{3,4})\s*[xX×]\s*(\d{3,4})\s*px", spec["image_dimensions"][0])
            if px_match:
                img_req["width"] = int(px_match.group(1))
                img_req["height"] = int(px_match.group(2))
        assets.append({
            "asset_id": "hero_image",
            "asset_type": "image",
            "asset_role": "hero_image",
            "item_type": "group" if spec["min_cards"] else "individual",
            "required": True,
            "requirements": img_req or None,
        })

    # Video asset
    if "video" in asset_types or spec["video_requirements"]:
        vid_req: dict = {}
        if spec["video_requirements"]:
            dur = re.search(r"(\d+)\s*sec", spec["video_requirements"], re.I)
            if dur:
                vid_req["max_duration_sec"] = int(dur.group(1))
            size = re.search(r"(\d+)\s*mb", spec["video_requirements"], re.I)
            if size:
                vid_req["max_size_mb"] = int(size.group(1))
        assets.append({
            "asset_id": "hero_video",
            "asset_type": "video",
            "asset_role": "hero_video",
            "item_type": "individual",
            "required": "video" in asset_types,
            "requirements": vid_req or None,
        })

    # Text assets — use max text limits from all variants
    for field, role, asset_id in [
        ("title",       "headline",       "headline"),
        ("description", "body_text",      "body_text"),
        ("button",      "call_to_action", "call_to_action"),
        ("footer",      "footer",         "footer"),
        ("form_title",  "form_title",     "form_title"),
    ]:
        if field in tl:
            assets.append({
                "asset_id": asset_id,
                "asset_type": "text",
                "asset_role": role,
                "item_type": "individual",
                "required": field == "title",
                "requirements": {"max_length": tl[field]},
            })

    return assets


# ---------------------------------------------------------------------------
# Build AdCP-schema renders[] from available_sizes
# ---------------------------------------------------------------------------

def build_renders(spec: dict) -> list[dict]:
    renders = []
    # Use available_sizes if present
    for i, sz in enumerate(spec["available_sizes"]):
        renders.append({
            "role": "primary" if i == 0 else "companion",
            "dimensions": sz,
        })
    # If no available_sizes, try to extract dimensions from image_dimensions
    if not renders and spec["image_dimensions"]:
        for dim_text in spec["image_dimensions"]:
            for m in re.finditer(r"(\d{3,4})\s*[xX×]\s*(\d{3,4})", dim_text):
                w, h = int(m.group(1)), int(m.group(2))
                # Skip very small or video-like dimensions
                if w >= 100 and h >= 50:
                    renders.append({"role": "primary", "dimensions": {"width": w, "height": h}})
                    break
    # Fallback
    if not renders:
        renders = [{"role": "primary", "dimensions": None}]
    return renders


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

# Map TOC anchor href -> section anchor id (some differ slightly)
ANCHOR_MAP = {
    "#Carousel_Standard":               "Carousel_Standard",
    "#with_highlight_on":               "with_highlight_on",
    "#with_highlight_off":              "with_highlight_off",
    "#Carousel_Overlay":                "Carousel_Overlay",
    "#Carousel_Flip":                   "Carousel_Flip",
    "#Carousel_Skinny":                 "Carousel_Skinny",
    "#Vertical_Video":                  "Vertical_Video",
    "#List":                            "List",
    "#Feature_Scrolled_Ad":             "Feature_Scrolled_Ad",
    "#Lead_Gen_Ad":                     "Lead_Gen_Ad",
    "#Ad_Single":                       "Ad_Single",
    "#Single_Native_Display_Ad":        "Single_Native_Display_Ad",
    "#Tiles_Format":                    "Tiles_Format",
    "#gallery":                         "gallery",
    "#Mask_Scroll":                     "Mask_Scroll",
    "#Social_Display_Ad_Facebook":      "Social_Display_Ad_Facebook",
    "#Social_Display_Ad_Facebook_Carousel": "Social_Display_Ad_Facebook_Carousel",
    "#Social_Display_Ad_Instagram":     "Social_Display_Ad_Instagram",
    "#Social_Display_Ad_LinkedIn":      "Social_Display_Ad_LinkedIn",
    "#Social_Display_Ad_Tik_Tok":       "Social_Display_Ad_Tik_Tok",
    "#Comparison_Slider":               "Pro_V9_Gallery",      # anchor mismatch
    "#Product_Color":                   "Product_Color",
    "#3D_Cube":                         "3D_Cube",
    "#Choose_&_Scratch":                "Choose_&_Scratch",
    "#Vertical_Stories":                "Pro_V_9_Image_Shifter",
    "#Card_Swiper":                     "Card_Swiper",
    "#Full_Image_Gallery":              "Full_Image_Gallery",
    "#Tap_to_Win_Game":                 "Tap_to_Win_Game",
    "#3D_Parallax":                     "3D_Parallax",
    "#Tilt_Move":                       "Tilt_Move",
    "#Shake_&_Reveal":                  "Shake_&_Reveal",
    "#Horizontal_Video":                "Horizontal_Video",
    "#Video_Hotspot":                   "Video_Hotspot",
    "#Scratch_&_Show":                  "Scratch_&_Show",
    "#Combo_&_Mix":                     "Combo_&_Mix",
    "#ChatBot":                         "ChatBot",
    "#App_Download":                    "App_Download",
    "#Countdown":                       "Countdown",
    "#Card_Swiper_with_Text":           "Card_Swiper_with_Text",
    "#Marketplace_Product_Gallery_with_Video": "Marketplace_Product_Gallery_with_Video",
    "#product_carousel":                "product_carousel",
    "#product_carousel_with_location":  "product_carousel_with_location",
    "#Flip":                            "Flip",
    "#ProductGallerywithVideo":         "ProductGallerywithVideo",
    "#360view":                         "360view",
    "#MixandMatch":                     "MixandMatch",
    "#GallerySlideShow":                "GallerySlideShow",
    "#SingleImageScratch":              "SingleImageScratch",
}


def extract_preview_links(section) -> list[str]:
    links = []
    if not section:
        return links
    # Search broadly — traverse next 50 elements until the next section heading
    node = section
    for _ in range(50):
        node = node.find_next()
        if not node:
            break
        # Stop at next format section (h2, or a strong tag with font-size 18px that's a new heading)
        if node.name in ('h2', 'h3'):
            break
        # Stop if we hit another section anchor that's a known format id
        if node.get('id') and node.get('id') in ANCHOR_MAP.values():
            break
        if node.name == 'a' and node.get('href', ''):
            href = node['href']
            if 'enzymic.co/previews' in href and href not in links:
                links.append(href)
    return links


def parse_all_formats(html_path: str) -> list[dict]:
    soup = BeautifulSoup(
        Path(html_path).read_text(encoding="utf-8", errors="replace"),
        "html.parser"
    )

    ol = soup.find("ol")
    toc_items = ol.find_all("li") if ol else []

    formats = []
    for idx, li in enumerate(toc_items, start=1):
        # Some items have two <a> tags — first empty, second has the name
        a_tag = next((a for a in li.find_all("a") if a.get_text(strip=True)), None)
        if not a_tag:
            continue

        name = a_tag.get_text(strip=True)
        href = a_tag.get("href", "")

        # Resolve anchor id
        anchor_id = ANCHOR_MAP.get(href) or href.lstrip("#")

        section = soup.find(id=anchor_id)
        if not section:
            print(f"  [WARN] section not found for '{name}' (anchor={anchor_id})")
            spec = {
                "available_sizes": [], "text_limits": {}, "min_cards": None,
                "image_dimensions": [], "video_requirements": None,
                "dco_available": False, "ad_fields": {}, "notes": [],
            }
        else:
            table = section.find_next("table")
            spec = parse_spec_table(table) if table else {
                "available_sizes": [], "text_limits": {}, "min_cards": None,
                "image_dimensions": [], "video_requirements": None,
                "dco_available": False, "ad_fields": {}, "notes": [],
            }

        preview_links = extract_preview_links(section) if section else []

        assets = build_assets(name, spec)
        renders = build_renders(spec)

        fmt = {
            "format_id": {
                "agent_url": "https://creative.adcontextprotocol.org",
                "id": make_format_id(name, idx),
            },
            "name": name,
            "type": infer_type(name),
            "is_responsive": False,
            "dco_available": spec["dco_available"],
            "assets": assets,
            "renders": renders,
            "preview_urls": preview_links,
            "specs": {
                "text_limit_variants": spec["text_limit_variants"],
                "min_cards_by_size": spec["min_cards_by_size"],
                "image_dimensions": spec["image_dimensions"],
                "feature_image_dimensions": spec["feature_image_dimensions"],
                "video_requirements": spec["video_requirements"],
                "additional_requirements": spec["additional_requirements"],
                "optional_requirements": spec["optional_requirements"],
            },
        }

        formats.append(fmt)
        print(f"  [{idx:2d}] {name} — {len(assets)} assets, {len(renders)} renders")

    return formats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    html_file = "adzymic_raw.html"
    output_file = "creative_formats.json"

    print(f"Parsing {html_file} ...")
    formats = parse_all_formats(html_file)

    output = {
        "formats": formats,
        "generated_at": datetime.now().isoformat(),
        "source": "Adzymic Freshdesk — parsed from adzymic_raw.html",
        "total_formats": len(formats),
    }

    Path(output_file).write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"\nDone — {len(formats)} formats written to {output_file}")


if __name__ == "__main__":
    main()
