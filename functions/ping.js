// POST /ping — receives beacon data (no auth; beacons can't log in)
// Each ping = 1 KV read + 1 KV write.

const MAX_PINGS = 1000;

async function getState(env) {
  const raw = await env.BEACON_KV.get("state");
  if (raw) {
    try { return JSON.parse(raw); } catch {}
  }
  return { pings: [], notes: {}, labels: {} };
}

export async function onRequestPost(context) {
  const { request, env } = context;
  let data;
  try { data = await request.json(); } catch {}
  if (!data) {
    return new Response(JSON.stringify({ error: "no data" }), { status: 400, headers: { "Content-Type": "application/json" } });
  }

  const state = await getState(env);
  state.pings.push(data);
  if (state.pings.length > MAX_PINGS) state.pings = state.pings.slice(-MAX_PINGS);
  await env.BEACON_KV.put("state", JSON.stringify(state));

  return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "Content-Type": "application/json" } });
}
