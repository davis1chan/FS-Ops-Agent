import os, json, time, requests
from flask import Flask, request, jsonify, abort

app = Flask(__name__)

# ✅ Read from ENV VAR NAMES (no literals)
SHOP_BASE_URL = os.getenv("SHOP_BASE_URL")          # e.g. https://<your>.myshopify.com
ADMIN_TOKEN   = os.getenv("SHOP_ADMIN_TOKEN")       # Shopify Admin API token (private app/custom app)
INTERNAL_KEY  = os.getenv("FS_INTERNAL_API_KEY")    # your shared secret for this service

def require_api_key(req):
    # ✅ Fail closed: require key to be configured and present
    header_key = req.headers.get("x-api-key")
    if not INTERNAL_KEY or header_key != INTERNAL_KEY:
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
            # Bubble upstream GraphQL errors in a controlled way
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
