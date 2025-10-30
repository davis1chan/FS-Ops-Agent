import os, json, time, requests, hmac, base64
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

SHOP_BASE_URL = os.getenv("SHOP_BASE_URL")
ADMIN_TOKEN   = os.getenv("SHOP_ADMIN_TOKEN")

def require_api_key(req):
    expected = os.getenv("FS_INTERNAL_API_KEY", "")
    if not expected:
        abort(500, description="Server missing internal API key")

    header_key = req.headers.get("x-api-key", "")
    auth_hdr   = req.headers.get("Authorization", "") or ""

    ok_api = hmac.compare_digest(header_key, expected)

    ok_bearer = auth_hdr.startswith("Bearer ") and hmac.compare_digest(
        auth_hdr.split(" ", 1)[1], expected
    )

    ok_basic = False
    if auth_hdr.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_hdr.split(" ", 1)[1]).decode("utf-8")
            user, pwd = decoded.split(":", 1) if ":" in decoded else ("", "")
            ok_basic = hmac.compare_digest(pwd, expected)
        except Exception:
            pass

    if not (ok_api or ok_bearer or ok_basic):
        abort(401, description="Unauthorized")

def shopify_graphql(query, variables=None, max_retries=3):
    if not SHOP_BASE_URL or not ADMIN_TOKEN:
        abort(500, description="Server not configured (missing env vars).")

    url = f"{SHOP_BASE_URL.rstrip('/')}/admin/api/2025-01/graphql.json"
    headers = {
        "X-Shopify-Access-Token": ADMIN_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"query": query, "variables": variables or {}}

    backoff = 0.5
    for _ in range(max_retries):
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=20)
        if resp.status_code in (429, 502, 503):
            time.sleep(backoff); backoff *= 2; continue
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            abort(resp.status_code, description=str(e))

        data = resp.json()
        if "errors" in data:
            abort(502, description=json.dumps(data["errors"]))
        return data.get("data")

    abort(502, description="Upstream Shopify error (retries exhausted)")

@app.get("/health")
def health():
    return jsonify(ok=True)

@app.post("/query")
def query():
    require_api_key(request)
    body = request.get_json(force=True) or {}
    gql = body.get("query")
    variables = body.get("variables", {})
    if not gql:
        abort(400, description="Missing GraphQL 'query'.")
    data = shopify_graphql(gql, variables)
    return jsonify({"ok": True, "data": data})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
