export default {
  async scheduled(event, env, ctx) {
    const keepwarmUrl = env.WKAP_KEEPWARM_URL || "https://wkap.ai/";
    ctx.waitUntil(pingKeepwarm(keepwarmUrl));
  },

  async email(message, env, ctx) {
    const forwardTo = env.WKAP_FORWARD_TO || env.WKAP_CLOUDFLARE_FORWARD_TO || "playinc@gmail.com";
    const ingestUrl = env.WKAP_RENDER_INGEST_URL;
    const ingestSecret = env.WKAP_CLOUDFLARE_INGEST_SECRET;

    if (!ingestUrl || !ingestSecret) {
      console.error(
        JSON.stringify({
          event: "wkap_ingest_skipped",
          reason: "missing_worker_config",
          has_ingest_url: Boolean(ingestUrl),
          has_ingest_secret: Boolean(ingestSecret),
          message_id: message.headers.get("message-id") || "",
          subject: message.headers.get("subject") || "",
        })
      );
    } else {
      const rawBytes = await new Response(message.raw).arrayBuffer();
      const payload = {
        from: message.from,
        to: message.to,
        subject: message.headers.get("subject") || "",
        message_id: message.headers.get("message-id") || "",
        received_at: message.headers.get("date") || new Date().toUTCString(),
        raw_mime_base64: arrayBufferToBase64(rawBytes),
      };

      ctx.waitUntil(postToIngest(ingestUrl, ingestSecret, payload));
    }

    await message.forward(forwardTo);
  },
};

async function pingKeepwarm(keepwarmUrl) {
  try {
    const response = await fetch(keepwarmUrl, {
      method: "HEAD",
      headers: {
        "user-agent": "wkap-keepwarm/1.0",
      },
    });
    if (!response.ok) {
      console.error(
        JSON.stringify({
          event: "wkap_keepwarm_failed",
          status: response.status,
          status_text: response.statusText,
          keepwarm_url: keepwarmUrl,
        })
      );
    }
  } catch (error) {
    console.error(
      JSON.stringify({
        event: "wkap_keepwarm_failed",
        error: error && error.message ? error.message : String(error),
        keepwarm_url: keepwarmUrl,
      })
    );
  }
}

async function postToIngest(ingestUrl, ingestSecret, payload) {
  try {
    const response = await fetch(ingestUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-wkap-worker-secret": ingestSecret,
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const body = await response.text().catch(() => "");
      console.error(
        JSON.stringify({
          event: "wkap_ingest_failed",
          status: response.status,
          status_text: response.statusText,
          response_body: body.slice(0, 500),
          message_id: payload.message_id,
          subject: payload.subject,
        })
      );
    }
  } catch (error) {
    console.error(
      JSON.stringify({
        event: "wkap_ingest_failed",
        error: error && error.message ? error.message : String(error),
        message_id: payload.message_id,
        subject: payload.subject,
      })
    );
  }
}

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
