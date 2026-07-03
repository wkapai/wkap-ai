export default {
  async email(message, env, ctx) {
    const forwardTo = env.WKAP_FORWARD_TO || "playinc@gmail.com";
    const ingestUrl = env.WKAP_RENDER_INGEST_URL;
    const ingestSecret = env.WKAP_CLOUDFLARE_INGEST_SECRET;

    if (ingestUrl && ingestSecret) {
      const rawBytes = await new Response(message.raw).arrayBuffer();
      const payload = {
        from: message.from,
        to: message.to,
        subject: message.headers.get("subject") || "",
        message_id: message.headers.get("message-id") || "",
        received_at: message.headers.get("date") || new Date().toUTCString(),
        raw_mime_base64: arrayBufferToBase64(rawBytes),
      };

      ctx.waitUntil(
        fetch(ingestUrl, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-wkap-worker-secret": ingestSecret,
          },
          body: JSON.stringify(payload),
        })
      );
    }

    await message.forward(forwardTo);
  },
};

function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}
