import os
from dotenv import load_dotenv
from llm.bedrock_client import MODEL_ID, get_bedrock_client

load_dotenv()

print("Region:", os.getenv("AWS_REGION"))
print("Key ID:", os.getenv("AWS_ACCESS_KEY_ID", "NOT SET")[:8] + "...")
print("Model:", MODEL_ID)

try:
    client = get_bedrock_client()
    print("Boto3 client created OK")

    response = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": "Say hello in one word"}]}],
    )
    content = response["output"]["message"]["content"]
    print("Raw content blocks:", content)
    text = next((b["text"] for b in content if "text" in b), None)
    print("Response:", text)

except Exception as e:
    print("ERROR:", type(e).__name__, str(e))
