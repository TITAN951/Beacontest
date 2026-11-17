export async function onRequestGet() {
  return new Response(null, {
    status: 302,
    headers: {
      "Set-Cookie": "bt_auth=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
      "Location": "/"
    }
  });
}
