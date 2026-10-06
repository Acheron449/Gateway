/**
 * Auth0 SPA configuration, read from Vite build-time env vars.
 *
 * Auth0 sign-in is opt-in: when any of the three values is missing the app
 * boots exactly as before with local email/password auth. The audience is
 * mandatory — Auth0 issues *opaque* (non-JWT) access tokens without one, and
 * the backend can only verify a JWT.
 *
 *   VITE_AUTH0_DOMAIN     dev-abc123.us.auth0.com
 *   VITE_AUTH0_CLIENT_ID  <SPA application client id>
 *   VITE_AUTH0_AUDIENCE   <Auth0 API identifier, e.g. https://gateway-api>
 *
 * The backend mirrors this with AUTH0_DOMAIN / AUTH0_AUDIENCE.
 */
export const auth0Config = {
  domain: import.meta.env.VITE_AUTH0_DOMAIN ?? "",
  clientId: import.meta.env.VITE_AUTH0_CLIENT_ID ?? "",
  audience: import.meta.env.VITE_AUTH0_AUDIENCE ?? "",
};

/** True only when every value needed for a verifiable JWT sign-in is present. */
export const auth0Enabled = Boolean(
  auth0Config.domain && auth0Config.clientId && auth0Config.audience,
);
