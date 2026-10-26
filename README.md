# VFS Asset Scanner (Streamlit)

Phone-friendly two-photo asset scanner: Google Cloud Vision reads handwritten VT machine numbers and printed IMEI/serial labels. Staff must verify/correct both before submitting. Saves rows to Google Sheets and photos to Google Drive.

## Deploy like the OOS app
1. Create a **private** GitHub repository. Upload `app.py`, `requirements.txt`, and `.streamlit/secrets.toml.example`. **Never upload actual credentials or `secrets.toml`.**
2. Create a Google Cloud project, enable **Cloud Vision API**, **Google Sheets API**, and **Google Drive API**, and configure billing for Vision as required. Create a service account and download its JSON key securely.
3. Create a Google Sheet and a Drive folder. Share **both** with the service account email as **Editor**. Note: some Google Workspace policies restrict service account Drive uploads; a shared drive or delegated account may be required.
4. Copy `.streamlit/secrets.toml.example` to a private local file and fill in the sheet ID, folder ID, and service account JSON fields. In Streamlit Community Cloud, paste the completed TOML in **App settings → Secrets**; don't commit it to GitHub. The JSON private key must retain escaped `\n` characters in TOML.
5. In Streamlit Community Cloud, choose the GitHub repo and set main file to `app.py`. Deploy and open the HTTPS Streamlit URL on a phone.
6. Test with one asset and verify the sheet row, photo links, and employee confirmation process before staff rollout.

## Important
- The example ePort label `VJ600015743` is a **serial number**, not a 15-digit IMEI. Choose the correct ID type.
- OCR may misread handwriting; mandatory verification is intentional.
- Duplicate VT IDs are blocked based on existing sheet rows; concurrent submissions may still race.
- Vision and Google Cloud usage may incur charges.
- The app is not yet connected to your Google account or deployed; setup requires access to your GitHub, Google Cloud and Streamlit accounts.
- The app has no login gate. Restrict access using your deployment/authentication policy before sharing publicly.
