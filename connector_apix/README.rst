.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

==============
APIX Connector
==============

APIX EDI connector for receiving and sending eInvoices via APIX

Features
========
- Setup APIX account
- Use any invoice template for outgoing invoices
- Send sale invoices (as einvoice or via printing service)
- Send sale credit notes (refunds)
- Receive purchase invoices
- Receive purchase credit notes (refunds)


Configuration
=============
- Set up a connector backend from Connectors->APIX->Backends
- Start sending/receiving invoices

Usage
=====
\-

Known issues / Roadmap
======================
- Sending attachments is not supported
- markReceived is not working: we are re-fetching all invoices

Credits
=======

Contributors
------------

* Jarmo Kortetjärvi <jarmo.kortetjarvi@tawasta.fi>

Maintainer
----------

.. image:: https://tawasta.fi/templates/tawastrap/images/logo.png
   :alt: Oy Tawasta OS Technologies Ltd.
   :target: https://tawasta.fi/

This module is maintained by Oy Tawasta OS Technologies Ltd.
