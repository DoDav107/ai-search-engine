from src.clients.openai_client import client
ans = client.chat("Who can help me automate repetitive tasks in my business with AI?")
print("LENGTH:", len(ans))
print(repr(ans))