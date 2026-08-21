# Facebook Page setup

Everything needed to turn on the Facebook crosspost in [facebook_poster.py](../facebook_poster.py).
The code is already written and idle — with `FACEBOOK_PAGE_ID` / `FACEBOOK_PAGE_TOKEN`
unset it is a no-op, so nothing here can break the bot's main job.

Total time: about 30 minutes.

---

## Step 1 — Create the Page

Go to <https://www.facebook.com/pages/create>.

### Page name

Match the Telegram brand, but do **not** use "noon" on its own. Looking like the
merchant is an affiliate-account-termination risk (the same reason the static site's
palette stays off noon's yellow).

Pick one:

```text
عروض نون مصر
```

```text
Noon Hot Deals Egypt
```

```text
عروض نون مصر | Noon Hot Deals
```

### Category

Type `Shopping` and pick **Shopping & Retail** from the suggestions.
Optional second category: **Product/Service**.

### Bio

Copy this whole block. It includes the affiliate disclosure, which Facebook and
noon both expect, and the Telegram link:

```text
أقوى عروض وخصومات نون مصر، أول بأول 🔥
خصومات حقيقية على الموبايلات والأجهزة والمنتجات المنزلية والجمال.
كود خصم إضافي: gado

قناة تيليجرام: https://t.me/noon_hot_deals

الروابط هنا روابط تسويق بالعمولة.
```

If you changed the coupon via `NOON_COUPON_CODE`, or the channel handle via
`TELEGRAM_CHANNEL_ID`, edit those two lines to match before pasting.

### Publish it

After creating, open **Settings → Privacy → Page visibility** and make sure the
Page is **Published**. An unpublished Page rejects API posts with a permissions
error that looks unrelated.

---

## Step 2 — Create a Meta app

1. Go to <https://developers.facebook.com/apps> and click **Create app**.
2. Use case: **Other** → app type: **Business**.
3. Name it anything (e.g. `noon-deals-bot`). No products need to be added.
4. Open **App settings → Basic** and copy the **App ID** and **App secret**.
   You need both in step 4.

The app can stay in **Development mode** forever. App Review is only required to
post to Pages you do not administer — you own this one.

---

## Step 3 — Generate a user token

1. Open <https://developers.facebook.com/tools/explorer>.
2. Top right: select your app in the **Meta App** dropdown.
3. **User or Page** dropdown: leave it as **User Token**.
4. Under **Permissions**, add all three:
   - `pages_manage_posts`
   - `pages_read_engagement`
   - `pages_show_list`
5. Click **Generate Access Token**, log in, and grant access **to the Page you
   just created** (the dialog asks which Pages — tick it explicitly).
6. Copy the token. It is short-lived (about 1 hour), which is fine — the next two
   steps trade it for a permanent one.

---

## Step 4 — Exchange for a long-lived user token

Replace the three placeholders and run:

```bash
curl -s "https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_USER_TOKEN"
```

The response contains `access_token` — that is the long-lived user token
(about 60 days). Keep it for the next step only; it is not what goes in the secrets.

---

## Step 5 — Get the Page ID and the permanent Page token

```bash
curl -s "https://graph.facebook.com/v21.0/me/accounts?access_token=LONG_USER_TOKEN"
```

The response lists every Page you administer:

```json
{
  "data": [
    {
      "name": "Noon Hot Deals Egypt",
      "id": "123456789012345",
      "access_token": "EAAG..."
    }
  ]
}
```

- `id` → `FACEBOOK_PAGE_ID`
- `access_token` → `FACEBOOK_PAGE_TOKEN`

A Page token derived from a **long-lived** user token does not expire. Confirm it:
paste the token into <https://developers.facebook.com/tools/debug/accesstoken> and
check that **Expires** reads **Never**. If it shows a date, your user token in step 4
was still the short-lived one — redo step 4 and step 5.

---

## Step 6 — Smoke test locally

Before wiring CI, prove the token posts:

```bash
FACEBOOK_PAGE_ID=123456789012345 FACEBOOK_PAGE_TOKEN=EAAG... python -c "
from facebook_poster import post_to_facebook
print(post_to_facebook(
    {'name': 'test', 'sale_price': 225, 'original_price': 640, 'discount_pct': 65},
    'https://www.noon.com/egypt-en/'))"
```

- `True` — a post is live on the Page. Delete it manually.
- `False` — the Graph error is printed above it. Common ones:
  - `(#200) ... requires pages_manage_posts` — permission missing in step 3.
  - `Error validating access token ... session has expired` — used the short-lived token.
  - `(#10) ... not published` — the Page is still unpublished (end of step 1).

---

## Step 7 — Add the repository secrets

```bash
gh secret set FACEBOOK_PAGE_ID --body "123456789012345"
gh secret set FACEBOOK_PAGE_TOKEN --body "EAAG..."
```

Or via the web UI: **Settings → Secrets and variables → Actions → New repository secret**.

The workflow already reads both — see the `FACEBOOK_PAGE_ID` / `FACEBOOK_PAGE_TOKEN`
lines in [bot.yml](../.github/workflows/bot.yml). No code changes are needed.

---

## Step 8 — Verify on the next run

Trigger the workflow manually (**Actions → Noon Deals Bot → Run workflow**) and
watch the log. Successful crossposts are silent; failures print
`Facebook post failed: HTTP …` and do **not** fail the run — the crosspost swallows
its own errors on purpose, so a broken token degrades to "Telegram only" rather
than taking the bot down.

Then open the Page and confirm the deals appear as link posts with noon's own
preview card.

---

## Notes

- Posts are **link posts**, not photo posts: Facebook renders noon's preview card
  and the link stays clickable. Captions under photos are not clickable.
- Every posted URL goes through `with_affiliate_utms`, so Facebook traffic is
  attributed exactly like Telegram traffic.
- To turn the crosspost off again, delete the two secrets. Nothing else changes.
