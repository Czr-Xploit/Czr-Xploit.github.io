const GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize";
const GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token";
const ALLOWED_SITE = "https://czr-xploit.github.io";

const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Cache-Control": "no-store, no-cache, must-revalidate",
};

function secureResponse(body, init = {}) {
  const headers = { ...SECURITY_HEADERS, ...(init.headers || {}) };
  return new Response(body, { ...init, headers });
}

function log(request, action, detail) {
  const ts = new Date().toISOString();
  const ip = request.headers.get("CF-Connecting-IP") || "?";
  const country = request.headers.get("CF-IPCountry") || "?";
  const ua = (request.headers.get("User-Agent") || "?").slice(0, 80);
  console.log(JSON.stringify({ ts, action, detail, ip, country, ua }));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return secureResponse(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": ALLOWED_SITE,
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    if (request.method !== "GET") {
      log(request, "blocked", `method=${request.method} path=${url.pathname}`);
      return secureResponse("Method not allowed", { status: 405 });
    }

    // OAuth step 1: redirect to GitHub authorization
    if (url.pathname === "/oauth" || url.pathname === "/oauth/") {
      log(request, "oauth_start", "redirecting to GitHub");
      const scope = url.searchParams.get("scope") || "repo,user";
      const authUrl = new URL(GITHUB_AUTH_URL);
      authUrl.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
      authUrl.searchParams.set("scope", scope);
      const state = url.searchParams.get("state");
      if (state) authUrl.searchParams.set("state", state);
      return Response.redirect(authUrl.toString(), 302);
    }

    // OAuth step 2: exchange code for token
    if (url.pathname === "/oauth/callback" || url.pathname === "/callback") {
      const code = url.searchParams.get("code");
      if (!code) {
        log(request, "callback_fail", "missing code");
        return secureResponse("Missing code parameter", { status: 400 });
      }

      if (code.length > 100 || !/^[a-f0-9]+$/i.test(code)) {
        log(request, "callback_fail", "invalid code format");
        return secureResponse("Invalid code format", { status: 400 });
      }

      let tokenData;
      try {
        const tokenResponse = await fetch(GITHUB_TOKEN_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "User-Agent": "sveltia-cms-auth-worker",
          },
          body: JSON.stringify({
            client_id: env.GITHUB_CLIENT_ID,
            client_secret: env.GITHUB_CLIENT_SECRET,
            code,
          }),
        });
        tokenData = await tokenResponse.json();
      } catch (err) {
        log(request, "callback_fail", `github unreachable: ${err.message}`);
        return secureResponse("OAuth provider unavailable", { status: 502 });
      }

      if (tokenData.error) {
        log(request, "callback_fail", `github error: ${tokenData.error}`);
        return secureResponse(
          renderMessage("error", tokenData.error_description || tokenData.error),
          { status: 401, headers: { "Content-Type": "text/html;charset=utf-8" } }
        );
      }

      log(request, "callback_ok", "token issued");
      return secureResponse(
        renderMessage("success", JSON.stringify({ token: tokenData.access_token, provider: "github" })),
        { status: 200, headers: { "Content-Type": "text/html;charset=utf-8" } }
      );
    }

    // Health check
    if (url.pathname === "/" || url.pathname === "/health") {
      return secureResponse(
        JSON.stringify({ status: "ok" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    log(request, "not_found", url.pathname);
    return secureResponse("Not found", { status: 404 });
  },
};

function renderMessage(status, content) {
  const origin = JSON.stringify(ALLOWED_SITE);
  return `<!doctype html>
<html>
<head><title>OAuth</title></head>
<body>
<script>
(function() {
  var target = window.opener || window.parent;
  target.postMessage(
    'authorization:github:${status}:' + JSON.stringify(${
      status === "success" ? content : JSON.stringify({ error: content })
    }),
    ${origin}
  );
  window.close();
})();
</script>
</body>
</html>`;
}
