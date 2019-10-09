# -*- coding: utf-8 -*-
import base64
import hashlib
import logging
import datetime
import requests

from collections import OrderedDict
from cStringIO import StringIO
from lxml import etree as ET
from mimetypes import MimeTypes
from zipfile import ZipFile


from odoo import api, fields, models, _
from odoo.exceptions import Warning, ValidationError
from odoo.addons.queue_job.job import job
logger = logging.getLogger(__name__)


class ApixBackend(models.Model):
    # region Private attributes
    _name = 'apix.backend'
    _description = 'APIX Backend'
    _inherit = 'connector.backend'

    _sql_constraints = [
        ('company_uniq', 'unique(company_id)',
         'Company can have only one backend.'),
    ]

    _FIELD_STATES = {
        'confirmed': [('readonly', True)],
        'unconfirmed': [('readonly', False)],
    }
    # endregion

    # region Fields declaration
    # Backends start as unconfirmed
    state = fields.Selection(
        string='State',
        selection=[
            ('unconfirmed', 'Unconfirmed'),
            ('confirmed', 'Confirmed'),
        ],
        default='unconfirmed',
    )

    # Company for multicompany environments
    company_id = fields.Many2one(
        comodel_name='res.company',
        required=True,
        default=lambda s: s.env['res.users'].browse([s._uid]).company_id,
        states=_FIELD_STATES,
    )

    # Apix username (email)
    username = fields.Char(
        string='Username',
        required=True,
        states=_FIELD_STATES,
    )

    # Apix password
    password = fields.Char(
        string='Password',
        required=True,
        copy=False,
        states=_FIELD_STATES,
    )

    # Apix API version
    version = fields.Selection(
        string='Version',
        selection=[('1.14', 'v1.14')],
        default='1.14',
        required=True,
        states=_FIELD_STATES,
    )

    # Apix environment
    environment = fields.Selection(
        string='Environment',
        selection=[('test', 'Test'), ('production', 'Production')],
        default='test',
        required=True,
        states=_FIELD_STATES,
    )

    # An optional prefix for business ids.
    # Apix may assign this to virtual operators
    prefix = fields.Char(
        string='Prefix',
        states=_FIELD_STATES,
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

    # The "business id".
    # This can be plain business id or a business id with a prefix
    business_id = fields.Char(
        string='Business ID',
        compute='compute_business_id',
    )

    # Qualifier for the identification; y-tunnus, orgnr etc.
    # Usually business id (y-tunnus)
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

    # Odoo-settings
    support_email = fields.Char(
        string='Support email',
        help='Replaces "servicedesk@apix.fi" with this address, if set',
    )

    invoice_template_id = fields.Many2one(
        comodel_name='ir.actions.report.xml',
        domain=[('model', '=', 'account.invoice')],
        string='Invoice template',
        help='Report template used when sending invoices via APIX',
        required=True,
        default=lambda s: s.env.ref('account.account_invoices'),
    )
    # endregion

    def compute_business_id(self):
        for record in self:
            prefix = record.prefix or ''
            business_id = prefix + record.company_id.company_registry
            record.business_id = business_id

    # region Action methods
    def action_authenticate(self):
        # A helper method for testing the authentication
        for record in self:
            record.RetrieveTransferID()
            record.AuthenticateByUser()

            # Everything is fine (no errors). Set this as confirmed
            record.state = 'confirmed'

    def action_reset_authentication(self):
        # A helper method for resetting the authentication
        for record in self:
            record.transfer_id = False
            record.transfer_key = False
            record.company_uuid = False
            record.state = 'unconfirmed'

    def action_cron_einvoice_fetch(self):
        for backend in self.search([]):
            backend.action_einvoice_fetch()

    def action_einvoice_fetch(self):
        for record in self:
            # Add fetching to queue
            job_desc = _("APIX fetch invoices for '%s'") % record.name
            record.with_delay(description=job_desc).list_invoices(refetch=False)

    def action_einvoice_refetch(self):
        for record in self:
            # Add fetching to queue
            job_desc = _("APIX refetch invoices for '%s'") % record.name
            record.with_context(company_id=record.company_id.id).with_delay(
                description=job_desc).list_invoices(refetch=True)

    @api.multi
    @job
    def list_invoices(self, refetch=False):
        """
        Fetch list of invoices from APIX
        This will always fetch everything as there is no filter options.
        Filtering should be added when it will become available

        :param refetch: Re-fetch already downloaded invoices
        :return:
        """
        self.ensure_one()

        # Fetch einvoices
        invoices = self.ListInvoiceZIPs()

        logger.debug(
            'Invoice XML: %s' % ET.tostring(invoices, pretty_print=True))
        for invoice in invoices.findall('.//Group'):
            storage_id = \
                invoice.find(".//Value[@type='StorageID']").text
            storage_key = \
                invoice.find(".//Value[@type='StorageKey']").text
            storage_status = \
                invoice.find(".//Value[@type='StorageStatus']").text

            if storage_status == 'UNRECEIVED' \
                    or refetch and storage_status == 'RECEIVED':
                job_desc = _("APIX import invoice '%s'") % storage_id
                self.with_delay(description=job_desc)\
                    .download_invoice(storage_id, storage_key)

    @api.multi
    @job
    def download_invoice(self, storage_id, storage_key):
        self.ensure_one()

        # Download invoice
        self.Download(storage_id, storage_key)

    # endregion

    def get_digest(self, values):
        # Returns the digest needed for requests
        digest_src = ''

        for value in values:
            digest_src += values[value] + '+'

        # Strip the last "+"
        digest_src = digest_src[:-1]
        logger.debug('Calculating digest from %s' % digest_src)
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
        # Please note that variables should always be in OrderedDict,
        # as APIX API expects the variables in a certain order

        terminal_commands = ['list', 'list2', 'receive', 'download', 'metadata']

        if self.environment == 'production':
            if command in terminal_commands:
                url = "https://terminal.apix.fi/"
            else:
                url = "https://api.apix.fi/"
        else:
            if command in terminal_commands:
                url = "https://test-terminal.apix.fi/"
            else:
                url = "https://test-api.apix.fi/"

        url += "%s?" % command

        for key, value in variables.iteritems():
            url += "%s=%s&" % (key, value)  # Add variables to the url

        if variables:
            url = url.rstrip('&')  # Strip the last &

        logger.debug('Using url %s' % url)

        return url

    def get_values_from_url(self, url):
        response = requests.get(url)
        html = response.text.encode('latin-1')
        root = ET.fromstring(html)

        # Get response status
        res_status = " ".join(
            [status.text for status in root.findall('Status')]
        )
        res_status_code = " ".join(
            [status.text for status in root.findall('StatusCode')]
        )
        res_free_text = " ".join(
            [status.text for status in root.findall('FreeText')]
        )

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

        if type(response) == list:
            # For some reason the res can also be a list with one dict in it (?)
            response = response[0]

        if response:
            self.customer_id = response.get('IdCustomer', False)
            self.customer_number = response.get('CustomerNumber', False)
            self.contact_person = response.get('ContactPerson', False)
            self.contact_email = response.get('Email', False)
            self.owner_id = response.get('OwnerId', False)

    def get_default_url_attributes(
            self,
            show_soft=True,  # Software
            show_ver=True,  # Software version
            storage_id=False,  # StorageID
            storage_key=False,  # StorageKey
            mark_received=False,  # Mark invoice as received
    ):
        values = OrderedDict()

        if show_soft:
            values['soft'] = "Standard"

        if show_ver:
            values['ver'] = "1.0"

        if mark_received:
            values['markReceived'] = 'yes'

        # Use SID OR TraID, never both
        if storage_id:
            values['SID'] = storage_id
        else:
            values['TraID'] = self.transfer_id

        values['t'] = self.get_timestamp()

        if storage_key:
            values['StorageKey'] = storage_key
        else:
            values['TraKey'] = self.transfer_key

        # Get the digest hash
        values['d'] = self.get_digest(values)

        # Remove TransferKey and StorageKey. We don't want them to the url
        values.pop("TraKey", None)
        values.pop("StorageKey", None)

        logger.debug('Using values %s' % values)

        return values

    def SendInvoiceZIP(self, payload):
        logger.debug("APIX SendInvoiceZIP")
        values = self.get_default_url_attributes()

        command = 'invoices'
        url = self.get_url(command, values)

        # Post the file to the server
        res = requests.put(url, data=payload)
        res.raise_for_status()

        utf8_parser = ET.XMLParser(encoding='utf-8')
        res_etree = ET.fromstring(res.text.encode('utf-8'), parser=utf8_parser)

        self.validateResponse(res_etree)

        return res_etree

    def ListInvoiceZIPs(self):
        logger.debug("APIX ListInvoiceZIPs")

        values = self.get_default_url_attributes(
            show_soft=False, show_ver=False
        )

        command = 'list2'
        url = self.get_url(command, values)

        # Get invoices from sever
        res = requests.get(url)
        res.raise_for_status()

        utf8_parser = ET.XMLParser(encoding='utf-8')
        res_etree = ET.fromstring(res.text.encode('utf-8'), parser=utf8_parser)

        return res_etree

    def Download(self, storage_id, storage_key):
        logger.debug("APIX Download")
        values = self.get_default_url_attributes(
            show_soft=False,
            show_ver=False,
            mark_received=False,
            storage_id=storage_id,
            storage_key=storage_key,
        )

        command = 'download'
        url = self.get_url(command, values)

        # Download invoice from sever
        res = requests.get(url)
        res.raise_for_status()

        zip_file = ZipFile(StringIO(res.content))
        mime = MimeTypes()

        Attachment = self.env['ir.attachment']

        finvoice=False
        attachment_ids = list()
        for file_name in zip_file.namelist():
            # Save to attachments without res_id
            values = dict(
                name=file_name,
                datas_fname=file_name,
                type='binary',
                datas=base64.b64encode(zip_file.read(file_name)),
                res_model='account.invoice',
                mimetype=mime.guess_type(file_name),
                company_id=self.company_id.id,
            )

            attachment_id = Attachment.create(values)
            if file_name == 'invoice.xml':
                finvoice = attachment_id
            else:
                attachment_ids.append(attachment_id)

        self.env['apix.account.invoice'].import_finvoice(
            finvoice, attachment_ids);

    def validateResponse(self, response):
        logger.debug('Response: %s' % ET.tostring(response))

        response_status = response.find('.//Status')

        if response_status is None:
            raise ValidationError(
                _('Invalid response: response status not found')
            )

        logger.debug("Response status: '%s'" % response_status.text)

        if response_status.text == 'ERR':
            try:
                error = response.find(".//Value[@type='ValidateText']").text
            except:
                error = _('Unknown error')

            try:
                statuscode = response.find('.//StatusCode').text
            except:
                statuscode = _('Unknown status code')

            msg = 'API Error (%s): %s' % \
                  (statuscode , error)

            # Replace the support address shown in the message
            if self.support_email:
                msg = msg.replace('servicedesk@apix.fi', self.support_email)

            raise ValidationError(msg)

        elif response_status == 'OK':
            # Response is OK, no actions
            return
