import base64, io, json, os, requests
from PIL import Image, ImageDraw

img = Image.new("RGB", (96, 96), (220, 30, 30))
d = ImageDraw.Draw(img)
d.rectangle([24, 24, 72, 72], fill=(20, 60, 220))
buf = io.BytesIO(); img.save(buf, "PNG")
b64 = base64.b64encode(buf.getvalue()).decode()

KEY = os.environ.get("MIMO_API_KEY", "")
if not KEY:
    raise SystemExit("MIMO_API_KEY 未配置；未发起网络请求")
for model in ["mimo-v2.6-pro", "mimo-v2.6-flash", "mimo-v2.6-pro-ultraspeed"]:
    payload = {"model": model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "图里有哪些颜色和形状？一句话。"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}], "max_tokens": 200}
    try:
        r = requests.post("https://api.xiaomimimo.com/v1/chat/completions",
                          headers={"Authorization": "Bearer " + KEY}, json=payload, timeout=60)
        print(model, r.status_code, r.text[:300].replace("\n", " "))
    except Exception as e:
        print(model, "ERR", e)
