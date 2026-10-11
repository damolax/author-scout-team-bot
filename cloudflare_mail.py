"""Cloudflare Email Sending transport. No SMTP ports or Google OAuth required."""
import json
import re
from email.utils import formataddr
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def send(account, token, recipient, subject, body):
    account_id = str(account.get('smtp_username') or '').strip()
    if not re.fullmatch(r'[a-fA-F0-9]{32}', account_id):
        raise ValueError('Enter the 32-character Cloudflare Account ID, not the Zone ID.')
    payload = {'from': formataddr((account.get('sender_name') or '', account['email'])),
               'to': recipient, 'subject': subject, 'text': body}
    if account.get('reply_to'):
        payload['headers'] = {'Reply-To': account['reply_to']}
    req = Request(f'https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send',
                  data=json.dumps(payload).encode(), method='POST',
                  headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'Cloudflare rejected sending (HTTP {exc.code}). Check Email Sending activation, domain verification, token permissions and account limits.') from None
    except (URLError, TimeoutError):
        raise RuntimeError('Cloudflare did not confirm sending. Check its email logs before retrying to avoid a duplicate.') from None
    if result.get('success') is not True:
        raise RuntimeError('Cloudflare did not accept the email. Check your Email Sending dashboard.')
    delivery = result.get('result') or {}
    if delivery.get('permanent_bounces'):
        raise RuntimeError('Cloudflare reported a permanent bounce. Check the recipient address.')
    if recipient not in delivery.get('delivered', []) + delivery.get('queued', []):
        raise RuntimeError('Cloudflare did not confirm this recipient. Check its email logs before retrying.')
