# ozbargain-tracker
Track new posts on ozbargain

## Scheduling the scraper

The scraper is scheduled by GitHub Actions every 6 hours. The workflow also
updates a weekly keepalive marker so GitHub does not disable the scheduled
workflow after long periods without deal changes.

For local testing, use:

```sh
RESEND_API_KEY=... scripts/run_ozbargain_scraper.sh
```

The runner creates or refreshes `.venv`, installs `requirements.txt`, and runs
`alert_on_new_posts.py` with the default Gaming PC Deals configuration. It
fails immediately if `RESEND_API_KEY` is not supplied by the runtime
environment.
