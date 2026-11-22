# iPhone & MacBook price tracker (Australia)

Checks JB Hi-Fi, The Good Guys, Harvey Norman, Officeworks, Amazon AU and Costco
every 2 hours. It emails when an iPhone 16, 17 or 17e (base models only, no Plus/Pro) or the latest MacBook Air (M5, 13" and 15")
hits its **lowest price seen so far across all stores**.

- Only the **base spec** of each model is tracked: the smallest storage for iPhones, and the smallest storage + RAM for each MacBook size and chip. Every colour of a model counts as the same model, so the cheapest colour wins. To track every storage option, set `LOWEST_SPEC_ONLY = False` in `config.py`.
  For example, *iPhone 17 Pro 256GB* or *MacBook Air 13" M5 16GB/512GB*.
- The **first run** only records starting prices and doesn't send an email.
- If a store can't be read for about 12 hours straight, it sends one warning email.
- Every morning (first check after 8am Perth time) it sends a daily summary: the cheapest price for each model right now, the change since yesterday, and a ⭐ on any model at its lowest price seen.

## Setup (about 10 minutes)

1. **Create a repo** on GitHub and upload every file in this folder, keeping the
   `.github/workflows/` folder. Make the repo **public** if you can: public repos
   get unlimited free Actions minutes. The emails and password stay hidden in
   secrets; the only public file is the price history.
2. **Gmail app password.** Use a Gmail account to send from. Turn on
   2-Step Verification, then go to Google Account → Security → *App passwords*,
   create one and copy the 16-character code.
3. **Add secrets.** In the repo, open Settings → Secrets and variables → Actions → *New repository secret*:
   | Name | Value |
   |---|---|
   | `SMTP_USER` | the Gmail address that sends the alerts |
   | `SMTP_PASSWORD` | the 16-character app password |
   | `ALERT_TO` | Dad's email (add more with commas: `a@x.com,b@y.com`) |
4. **Allow saving.** Settings → Actions → General → *Workflow permissions* → **Read and write** → Save.
5. **Test it.** Open the Actions tab → *Check prices* → **Run workflow**. Open the run log;
   it shows how many matching offers came from each store.

## Changing things

Edit `config.py`:

- **Models:** `IPHONE_MODELS` and `MACBOOK_LINES`
- **Stores and their search URLs:** `RETAILERS`
- **Minimum drop before an email:** `MIN_DROP`

To change how often it checks, edit the `cron` line in `.github/workflows/check.yml`.

## Limits

- **Store support varies.** JB Hi-Fi phones are read straight from JB's product
  feed, which is very reliable. Every other store is read by loading its search page in a hidden browser.
  Harvey Norman, Amazon and Costco sometimes block that kind of traffic. If they do,
  you'll get the warning email, and the other stores keep working.
- **Search results.** Only the first page of each search is read, so a store with lots of
  accessories mixed into its results can miss a few models.
- **Odd drops.** A very large drop is marked "check this". It's usually a real sale but can be a
  marketplace seller or a misread price.
- **Apple Store not included.** Apple only shows a fixed "From $X" price per model, so it's never the cheapest anyway.
