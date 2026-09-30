# Connecting Your WhatsApp Number (~15 minutes)

This guide connects a phone number to the voice receptionist so customers can
message it on WhatsApp and get instant AI replies. No coding needed — just
follow the clicks.

> **IMPORTANT — which number to use**
> Your number **+92 330 1529102** (03301529102, Jazz, Pakistan) can be used,
> but only if it is **NOT currently used for personal WhatsApp chats**.
> Meta requires the registered number to be a spare number, or a number you
> fully migrate off the WhatsApp app (migrating deletes its personal chats
> and you can never use that number in the WhatsApp app again while it is
> connected here). Safest option: get a cheap spare Jazz/Zong SIM and use
> that.

## What you need before starting

1. A Facebook account (any personal account works).
2. The spare phone number (it must be able to receive an SMS or a call once,
   for verification).
3. This server running somewhere reachable from the internet (your computer
   with `uvicorn` is fine for testing; for real use it needs a host with a
   public URL — e.g. a VPS, Railway, or Render).

## Steps

### 1. Create a Meta developer account and app (3 min)
1. Go to **developers.facebook.com** and log in with your Facebook account.
2. Click **Get Started** if asked, accept the terms.
3. Click **Create App** → choose **Other** → **Business** → name it e.g.
   `Voice Receptionist` → Create.

### 2. Add the WhatsApp product (2 min)
1. In the app dashboard, find **WhatsApp** in the product list and click **Set up**.
2. Meta gives you a **free test phone number** immediately. You can test with
   it first and add your real number later.

### 3. Add your real phone number (3 min)
1. In the WhatsApp product panel, go to **API Setup**.
2. Under "Send and receive messages", click **Add phone number**.
3. Enter your spare number (**+92 330 1529102**), choose SMS or call
   verification, enter the 6-digit code you receive.
4. The number now appears in the "From" phone number list. Note the
   **Phone number ID** shown under it — you will need it.

### 4. Create a permanent access token (3 min)
The temporary token on the API Setup page expires in 24 hours. For the
receptionist you need a permanent one:
1. Go to **developers.facebook.com → your app → App Settings → Basic**.
   Copy the **App ID** and **App Secret** (keep these private).
2. Open the **Graph API Explorer** (developers.facebook.com/tools/explorer),
   select your app, and generate a token with permissions
   `whatsapp_business_messaging` and `whatsapp_business_management`.
3. Exchange it for a long-lived token (valid ~60 days; refresh it before it
   expires, or use a System User token for a non-expiring one — see
   "Business Settings → System Users" in Meta's docs).
4. Save it as `WHATSAPP_TOKEN` in your `.env` file. Also set
   `WHATSAPP_PHONE_NUMBER_ID` to the Phone number ID from step 3.

### 5. Connect the webhook (3 min)
1. In the WhatsApp product panel, go to **Configuration**.
2. Under **Webhook**, click **Edit**:
   - **Callback URL:** `https://YOUR-SERVER-ADDRESS/webhook`
     (must be HTTPS; for local testing use a tunnel like ngrok:
     `ngrok http 8000`, then use the `https://...ngrok.io/webhook` URL)
   - **Verify token:** any secret phrase you invent, e.g.
     `my-secret-verify-123`. Save the SAME phrase as
     `WHATSAPP_VERIFY_TOKEN` in your `.env`.
3. Click **Verify and Save**. If it fails, check the URL is reachable and the
   verify token matches exactly.

### 6. Subscribe to messages (1 min)
1. Still on the **Configuration** page, under **Webhook fields**, click
   **Manage** next to `messages`.
2. Tick the **messages** checkbox and save. (This is what delivers incoming
   customer texts and voice notes to the app.)

### 7. Test it (2 min)
1. From your personal phone, send a WhatsApp message to the business number,
   e.g. `Salam, kal 5 baje ka time mil sakta hai?`
2. You should get an AI reply within seconds.
3. Open the dashboard at `http://YOUR-SERVER-ADDRESS:8000` — the conversation
   appears under Conversations.

You can also test sending from the server with the Graph API directly:

```bash
curl -X POST "https://graph.facebook.com/v21.0/PHONE_NUMBER_ID/messages" \
  -H "Authorization: Bearer WHATSAPP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messaging_product":"whatsapp","to":"923001234567",
       "type":"text","text":{"body":"Test from the server"}}'
```

## Mapping the number to a business config

If you run several businesses from one server, set the optional
`whatsapp_phone_number_id` field in each `businesses/*.json` to that
business's Phone number ID. Incoming messages are then routed to the right
config automatically. With a single business, no mapping is needed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Verify and Save" fails | Callback URL must be public HTTPS and return the challenge; check `WHATSAPP_VERIFY_TOKEN` matches exactly |
| No incoming messages arrive | The `messages` webhook field is not subscribed (step 6) |
| Replies never send | `WHATSAPP_TOKEN` expired or wrong; `WHATSAPP_PHONE_NUMBER_ID` mismatch |
| 190 / OAuth errors in logs | Token expired — generate a fresh one (step 4) |

## Costs

Meta's WhatsApp Cloud API is free for the first 1,000 user-initiated
conversations per month; after that it is a few cents per conversation.
Receiving messages and the webhook are always free.
