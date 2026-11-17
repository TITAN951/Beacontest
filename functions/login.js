// POST /login — password check, sets auth cookie
// GET  /login — just bounce to the login page

const DEFAULT_PASSWORD = "c2admin"; // override with BEACON_PASSWORD env var in Pages settings

async function sha256hex(str) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(str));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function expectedPassword(env) {
  return env.BEACON_PASSWORD || DEFAULT_PASSWORD;
}

export async function makeToken(env) {
  return sha256hex("beacon-tracker:" + expectedPassword(env));
}

export async function onRequestGet() {
  return new Response(null, { status: 302, headers: { "Location": "/" } });
}


export async function onRequestPost(context) {
  const { request, env } = context;
  const form = await request.formData();
  const pw = form.get("password") || "";

  if (pw === expectedPassword(env)) {
    const token = await makeToken(env);
    return new Response(null, {
      status: 302,
      headers: {
        "Set-Cookie": `bt_auth=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800`,
        "Location": "/dashboard.html"
      }
    });
  }
  return new Response(null, { status: 302, headers: { "Location": "/?err=1" } });
}
