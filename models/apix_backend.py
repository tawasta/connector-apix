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

    # The identification used for sending and receiving
    transfer_id = fields.Char(
        string='Transfer id',
        readonly=True,
        copy=False,
    )

    # The password used for sending and receiving
    transfer_key = fields.Char(
        string='Transfer key',
        readonly=True,
        copy=False,
    )

    # An unique identifier assigned to the company
    company_uuid = fields.Char(
        string='Company UUID',
        readonly=True,
        copy=False,
    )

    # The "business id". This can be plain business id or a business id with a prefix
    business_id = fields.Char(
        string='Business ID',
        compute='compute_business_id',
    )

    # Qualifier for the identification; y-tunnus, orgnr etc. (usually 'y-tunnus')
    id_qualifier = fields.Char(
        string='ID Qualifier',
        selection=[('y-tunnus', 'Business ID')],
        default='y-tunnus',
        required=True,
        readonly=True
    )

    # IdCustomer
    customer_id = fields.Char(
        string='Customer ID',
    )
    # CustomerNumber
    customer_number = fields.Char(
        string='Customer number',
    )
    # ContactPerson
    contact_person = fields.Char(
        string='Contact person',
    )
    # Email
    contact_email = fields.Char(
        string='Contact email',
    )
    # OwnerId
    owner_id = fields.Char(
        string='Owner ID'
    )

    def compute_business_id(self):
        for record in self:
            prefix = record.prefix or ''
            business_id = prefix + record.company_id.company_registry
            record.business_id = business_id

    def action_retrieve_transfer_id(self):
        for record in self:
            record.RetrieveTransferID()

    def action_authenticate_by_user(self):
        for record in self:
            record.AuthenticateByUser()

    def get_digest(self, values):
        # Returns the digest needed for requests
        digest_src = ''

        for value in values:
            digest_src += values[value] + '+'

        # Strip the last "+"
        digest_src = digest_src[:-1]
        digest = 'SHA-256:' + hashlib.sha256(digest_src).hexdigest()

        return digest

    def get_password_hash(self):
        # Returns a hashed password
        password_hash = hashlib.sha256(self.password).hexdigest()

        return password_hash

    def get_timestamp(self):
        # Returns the timestamp in the correct format for the REST API

        now = datetime.datetime.today()

        # Construct the timestamp
        timestamp = now.strftime('%Y%m%d%H%M%S')

        return timestamp

    def get_url(self, command, variables={}):
        # Returns the REST URL based on the environment, command and variables
        # Please note that variables should always be in OrderedDict, as APIX API
        # expects the variables in a certain order

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


    # RetrieveTransferID API method
    def RetrieveTransferID(self):
        logger.debug('APIX RetrieveTransferId')

        values = OrderedDict()
        values['id'] = self.business_id
        values['idq'] = self.id_qualifier
        values['uid'] = self.username
        values['ts'] = self.get_timestamp()
        values['d'] = self.get_password_hash()

        # Get the digest hash
        values['d'] = self.get_digest(values)

        command = 'app-transferID'
        url = self.get_url(command, values)
        response = self.get_values_from_url(url)

        if response:
            self.transfer_id = response.get('TransferID', False)
            self.transfer_key = response.get('TransferKey', False)
            self.company_uuid = response.get('UniqueCompanyID', False)

    # AuthenticateByUser API method
    def AuthenticateByUser(self):
        logger.debug('APIX AuthenticateByUser')

        values = OrderedDict()
        values['uid'] = self.username
        values['t'] = self.get_timestamp()
        values['d'] = self.get_password_hash()

        # Get the digest hash
        values['d'] = self.get_digest(values)

        # Add pass to variables
        values['pass'] = self.password

        command = 'authuser'
        url = self.get_url(command, values)
        response = self.get_values_from_url(url)

        if response:
            self.customer_id = response.get('IdCustomer', False)
            self.customer_number = response.get('CustomerNumber', False)
            self.contact_person = response.get('ContactPerson', False)
            self.contact_email = response.get('Email', False)
            self.owner_id = response.get('OwnerId', False)