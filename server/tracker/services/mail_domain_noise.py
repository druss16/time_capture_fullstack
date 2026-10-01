"""
Which observed email domains are "probably automated" — vendors, SaaS
platforms and bulk senders rather than people the firm works with.

THIS IS THE FILE TO EDIT when a vendor keeps showing up in Settings → Email
domains above the fold, or when a real counterparty is wrongly tucked away
under "Probably automated". It only affects how the observed list is SORTED
and GROUPED on that screen; it never maps, ignores or un-matches anything.

Three signals, any one is enough:
  1. AUTOMATED_SUBDOMAIN_PREFIXES — the leftmost label of a SUBDOMAIN is a
     bulk-mail sending host (`send.calendly.com`, `em1.cloudflare.com`). Only
     applies when there is a subdomain: `email.com` itself is not judged by
     its own name.
  2. VENDOR_DOMAINS — known SaaS / platform / big-provider REGISTRABLE domains.
     Matched on the registrable domain, so `e.stripe.com` counts as stripe.com.
  3. AUTOMATED_LOCAL_PARTS — most stored sender addresses at the domain are
     noreply@/notifications@/billing@…. Only Gmail rows store `from_address`,
     so this is a signal where present and silent otherwise.

THE OVERRIDE (enforced in mail_domains.classify_automated): a domain with ANY
calendar meeting or ANY outbound mail is never automated, whatever list it is
on. Someone you met with or wrote to is a real relationship — and clio.com
may well BE a client of some firm.
"""
from __future__ import annotations

import re

# Leftmost label of a subdomain that marks a bulk / transactional sending host.
# `em\d*` covers SendGrid-style em1., em2847. hosts.
AUTOMATED_SUBDOMAIN_PREFIXES = frozenset({
    'mail', 'email', 'emails', 'e', 'em', 'send', 'updates', 'update', 'notify',
    'notifications', 'notification', 'news', 'newsletter', 'newsletters', 'info',
    'marketing', 'mkt', 'bounce', 'bounces', 'followups', 'user', 'ar', 'dp',
    'reply', 'replies', 'noreply', 'no-reply', 'mailer', 'mailers', 'alerts',
    'txn', 'transactional', 'mg', 'sg', 'ses', 'msg', 'mailing',
})
_EM_HOST_RE = re.compile(r'^em\d+$')

# Registrable domains of vendors, SaaS platforms and big providers that mail a
# firm but are not (for nearly every firm) a client. Lower-case, no `www.`.
VENDOR_DOMAINS = frozenset({
    # Big providers / identity
    'google.com', 'googlemail.com', 'microsoft.com', 'microsoftonline.com', 'office.com',
    'office365.com', 'apple.com', 'amazon.com', 'amazonaws.com', 'facebookmail.com',
    'linkedin.com', 'twitter.com', 'x.com',
    # Payments / finance platforms
    'stripe.com', 'paypal.com', 'intuit.com', 'quickbooks.com', 'xero.com',
    'americanexpress.com', 'meliopayments.com', 'bill.com', 'gusto.com', 'adp.com',
    'paychex.com', 'square.com', 'squareup.com', 'expensify.com', 'ramp.com',
    'brex.com', 'chase.com',
    # Practice management / legal / tax software
    'clio.com', 'karbonhq.com', 'canopytax.com', 'taxdome.com', 'docusign.net',
    'docusign.com', 'thomsonreuters.com', 'cch.com', 'wolterskluwer.com',
    # Productivity / collaboration
    'notion.so', 'notion.com', 'slack.com', 'asana.com', 'dropbox.com', 'box.com',
    'zoom.us', 'calendly.com', 'typeform.com', 'typeform.io', 'github.com',
    'atlassian.com', 'atlassian.net', 'trello.com', 'monday.com', 'clickup.com',
    'hubspot.com', 'salesforce.com', 'zendesk.com', 'intercom.io', 'mailchimp.com',
    'figma.com', 'canva.com', 'loom.com', 'airtable.com',
    # Hosting / infra / dev tooling
    'hostinger.com', 'cloudflare.com', 'neon.tech', 'render.com', 'vercel.com',
    'netlify.com', 'godaddy.com', 'namecheap.com', 'squarespace.com', 'wix.com',
    'improvmx.com', 'sendgrid.net', 'mailgun.org', 'openai.com', 'anthropic.com',
    # Sales / data vendors
    'apollo.io', 'tryapollo.io', 'dnb.com', 'zoominfo.com',
})

# Sender local-parts (before the @) that are machine senders. Matched as a
# case-insensitive regex in the database against MailSignal.from_address.
# Deliberately NOT info@/hello@/support@/team@: small businesses — exactly a
# firm's clients — write from those.
AUTOMATED_LOCAL_PART_REGEX = (
    r'^(no-?reply|do-?not-?reply|donotreply|notifications?|notify|alerts?|'
    r'billing|receipts?|invoices?|newsletters?|news|marketing|mailer(-daemon)?|'
    r'bounces?|updates?|automated|system)([+._-][^@]*)?@'
)
# Share of stored sender addresses at a domain that must be automated.
AUTOMATED_LOCAL_PART_SHARE = 0.5


def is_automated_host_label(label: str) -> bool:
    label = (label or '').lower()
    return label in AUTOMATED_SUBDOMAIN_PREFIXES or bool(_EM_HOST_RE.match(label))
