# Facebook Page crosspost turned on

**Date:** 2026-08-21

## What

Created the Facebook Page *Noon Hot Deals Egypt*, produced its profile and cover
art, minted a non-expiring Page access token, and set `FACEBOOK_PAGE_ID` /
`FACEBOOK_PAGE_TOKEN` as repository secrets. `facebook_poster.py` had been written
and idle since 2026-07-28; no code changed to enable it.

Verified by posting a real link post to the Page through the Graph API and deleting
it (`{"success":true}`), and by `debug_token` reporting `expires_at: 0`.

New files: `brand/profile.svg`, `brand/profile.png`, `brand/cover.html`,
`brand/cover.png`, `docs/FACEBOOK-SETUP.md`.

## Mistakes

- **Took the Page ID from the Page URL.** `facebook.com/profile.php?id=61593516634356`
  looks authoritative, and that number was set as `FACEBOOK_PAGE_ID` and committed as
  a secret. It is a *profile* ID, not the Graph API Page ID. The real one
  (`1278507528683582`) only came back from `/me/accounts`. Nothing would have failed
  loudly — `post_to_facebook` swallows its errors on purpose, so the run would have
  stayed green while every crosspost 404'd. Only fetching the ID from the same call
  that mints the token caught it.
- **Followed the old token walkthrough for a new-style app.** The written steps
  (Graph API Explorer → tick three permissions → Generate) are for the pre-use-case
  app model. An app created today under *Manage everything on your Page* answers
  "no configuration enabled", and the OAuth dialog rejects `scope=` with
  `Invalid Scopes: pages_read_engagement, pages_manage_posts`. Three separate
  attempts were burned before the actual model became clear: **Facebook Login for
  Business ignores `scope` and requires a `config_id`**, and a permission must be
  added at the *use case* before it can be selected in a configuration.
- **Assumed `https://www.facebook.com/connect/login_success.html` still works as a
  redirect target.** Meta now rejects it outright: "This can't be a Facebook URL."
  The project's own GitHub Pages URL works fine as the redirect and needs nothing
  hosted — the token arrives in the URL fragment either way.
- **Drew an arrowhead with its legs pointing away from the shaft.** Rendered as a
  bracket glued to a line, not an arrow. Arrowhead legs point *back along* the
  shaft; at a 45° shaft that puts them near-axis-aligned, which looks wrong in the
  source and correct on screen.
- **First cover layout put the content off-centre**, so Facebook's mobile side-crop
  would have cut the headline. Cover content belongs in a centred ~1080×620 box,
  clear of the profile picture that overlays the lower-left on desktop.

## What worked

- Minting the token and reading the Page ID from the **same** `/me/accounts`
  response. One call, both values, no chance of pairing a right token with a wrong ID.
- `debug_token` as the completion check. `expires_at: 0` is the only proof the
  60-day user token was exchanged correctly; a Page token derived from a short-lived
  user token looks identical until it dies.
- Requesting **"Opt in to current Pages only"**. `granular_scopes` then pins all
  three permissions to this one Page, so a leaked token cannot reach a Page created later.
- Post-then-delete against the live Page as the smoke test. This machine has no real
  Python (`python` resolves to the Windows Store stub), so `facebook_poster.py` could
  not be run locally at all — curl against the same endpoint proved the same path.
- Rendering brand art by pointing headless Chrome at local SVG/HTML. No image
  library, no font files to ship, and the cover's Arabic shapes correctly because
  the browser does the shaping.

## Rules

- **Never read a Page ID out of a Facebook URL.** Take it from `/me/accounts`,
  the call that also returns the token.
- For any app created after the use-case migration: add the permission at
  **Use cases → Customize** first, then build a **Login for Business configuration**,
  then pass `config_id=` (never `scope=`) to the OAuth dialog.
- Use a redirect URI you own. `login_success.html` is dead.
- Verify a Page token with `debug_token` and require `expires_at: 0` before
  storing it. Anything else is a token that quietly dies in about an hour.
- A silent side channel needs a loud test. `post_to_facebook` never raises, so its
  failures never reach CI — prove the path by posting and deleting, not by a green run.
