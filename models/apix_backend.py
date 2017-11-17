# -*- coding: utf-8 -*-
import hashlib
import logging
import datetime
import requests
from lxml import etree as ET
from collections import OrderedDict

from odoo import api, fields, models
from odoo.exceptions import Warning
logger = logging.getLogger(__name__)


class ApixBackend(models.Model):
    _name = 'apix.backend'
    _description = 'APIX Backend'
    _inherit = 'connector.backend'

    company_id = fields.Many2one(
        comodel_name='res.company',
        required=True,
        default=lambda self: self.env['res.users'].browse([self._uid]).company_id,
    )

    username = fields.Char(
        string='Username',
        required=True,
    )

    password = fields.Char(
        string='Password',
        required=True,
        copy=False,
    )

    version = fields.Selection(
        string='Version',
        selection=[('1.14', 'v1.14')],
        default='1.14',
        required=True,
    )

    environment = fields.Selection(
        string='Environment',
        selection=[('test', 'Test'), ('production', 'Production')],
        default='test',
        required=True,
    )

    prefix = fields.Char(
        string='Prefix',
    )

    transfer_id = fields.Char(
        string='Transfer id',
        readonly=True,
        copy=False,
    )

    transfer_key = fields.Char(
        string='Transfer key',
        readonly=True,
        copy=False,
    )

    company_uuid = fields.Char(
        string='Company UUID',
        readonly=True,
        copy=False,
    )

    id_qualifier = fields.Char(
        string='ID Qualifier',
        compute='compute_id_qualifier',
    )

    def compute_id_qualifier(self):
        for record in self:
            prefix = record.prefix or ''
            id_qualifier = prefix + record.company_id.company_registry
            record.id_qualifier = id_qualifier

    def action_retrieve_transfer_id(self):
        for record in self:
            record.retrieve_transfer_id()

    def get_digest(self, values):
        digest_src = ''

        for value in values:
            digest_src += values[value] + '+'

        # Strip the last "+"
        digest_src = digest_src[:-1]
        digest = 'SHA-256:' + hashlib.sha256(digest_src).hexdigest()

        return digest

    def get_timestamp(self):
        # Returns the timestamp in the correct format for the REST API

        now = datetime.datetime.today()

        # Construct the timestamp
        timestamp = now.strftime('%Y%m%d%H%M%S')

        return timestamp

    def retrieve_transfer_id(self):
        logger.debug("APIX RetrieveTransferId")
        password_hash = hashlib.sha256(self.password).hexdigest()

        values = OrderedDict()
        values['id'] = self.id_qualifier
        values['idq'] = 'y-tunnus'  # qualifier for the identification; y-tunnus, orgnr etc. (usually 'y-tunnus')
        values['uid'] = self.username
        values['ts'] = self.get_timestamp()
        values['d'] = password_hash

        # Get the digest hash
        values['d'] = self.get_digest(values)

        url = self.get_url('app-transferID', values)
        response = self.get_values_from_url(url)

        if response:
            self.transfer_id = response.get('TransferID', False)
            self.transfer_key = response.get('TransferKey', False)
            self.company_uuid = response.get('UniqueCompanyID', False)

    def get_url(self, command, variables={}):
        # Returns the REST URL based on the environment, command and variables

        if self.environment == 'production':
            url = "https://api.apix.fi/"
        else:
            url = "https://test-api.apix.fi/"

        url += "%s?" % command

        for key, value in variables.iteritems():
            url += "%s=%s&" % (key, value)  # Add variables to the url

        if variables:
            url = url.rstrip('&')  # Strip the last &

        return url

    def get_values_from_url(self, url):
        response = requests.get(url)
        html = response.text.encode('latin-1')
        root = ET.fromstring(html)

        # Get response status
        res_status = " ".join([status.text for status in root.findall('Status')])
        res_status_code = " ".join([status.text for status in root.findall('StatusCode')])
        res_free_text = " ".join([status.text for status in root.findall('FreeText')])

        msg = "%s [%s]: %s" % (res_status, res_status_code, res_free_text)

        if res_status == "ERR":
            logger.warn(msg)  # Log error message and error
            raise Warning(res_free_text)  # Show the human readable part
        else:
            logger.debug(msg)

        groups = list()
        for group in root.iter('Group'):
            values = dict()
            for value in group.iter('Value'):
                values[value.attrib['type']] = value.text

            groups.append(values)

        # Only one item
        if len(groups) == 1:
            groups = groups[0]

        return groups
