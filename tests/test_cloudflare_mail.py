import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from cloudflare_mail import send

class CloudflareMailTests(unittest.TestCase):
    account = {'smtp_username': 'a'*32, 'email': 'sender@example.com', 'sender_name': 'Olalekan Oyekunle'}
    def test_exact_message_and_fixed_endpoint(self):
        with patch('cloudflare_mail.urlopen', return_value=io.BytesIO(json.dumps({'success':True,'result':{'queued':['reader@example.com']}}).encode())) as post:
            send(self.account, 'secret-token', 'reader@example.com', 'Subject', 'Halló\nExact body')
            req=post.call_args.args[0]
            self.assertEqual(req.full_url, 'https://api.cloudflare.com/client/v4/accounts/'+('a'*32)+'/email/sending/send')
            self.assertEqual(json.loads(req.data)['text'], 'Halló\nExact body')
    def test_invalid_account_never_connects(self):
        with patch('cloudflare_mail.urlopen') as post:
            with self.assertRaises(ValueError):send({**self.account,'smtp_username':'../other'},'token','reader@example.com','S','B')
            post.assert_not_called()
    def test_rejected_and_bounced_are_not_success(self):
        for data in [{'success':False},{'success':True,'result':{'permanent_bounces':['reader@example.com']}},{'success':True,'result':{}}]:
            with patch('cloudflare_mail.urlopen',return_value=io.BytesIO(json.dumps(data).encode())):
                with self.assertRaises(RuntimeError):send(self.account,'token','reader@example.com','S','B')
    def test_error_does_not_expose_token(self):
        with patch('cloudflare_mail.urlopen',side_effect=HTTPError('https://api.cloudflare.com',403,'secret-token',{},None)):
            with self.assertRaises(RuntimeError) as error:send(self.account,'secret-token','reader@example.com','S','B')
            self.assertNotIn('secret-token',str(error.exception))

if __name__=='__main__':unittest.main()
