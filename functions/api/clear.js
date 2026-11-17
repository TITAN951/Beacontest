// POST /api/clear — wipes all data (auth required)
const DEFAULT_PASSWORD = "c2admin";

async function sha256hex(str) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function cookieValue(request, name) {
  const m = (request.headers.get("Cookie") || "").match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return m ? m[1] : null;
}

export async function onRequestPost(context) {
  const { request, env } = context;
  const password = env.BEACON_PASSWORD || DEFAULT_PASSWORD;
  const token = await sha256hex("beacon-tracker:" + password);
  if (cookieValue(request, "bt_auth") !== token) {
    return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401, headers: { "Content-Type": "application/json" } });
  }

  await env.BEACON_KV.put("state", JSON.stringify({ pings: [], notes: {}, labels: {} }));

  return new Response(JSON.stringify({ status: "cleared" }), { status: 200, headers: { "Content-Type": "application/json" } });
}
