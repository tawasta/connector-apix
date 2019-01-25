# -*- coding: utf-8 -*-
import logging
import zipfile
import cStringIO
import base64

from odoo import fields, models, api
from odoo import _
from odoo.addons.queue_job.job import job
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

