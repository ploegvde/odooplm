# -*- coding: utf-8 -*-
##############################################################################
#
#    OmniaSolutions, ERP-PLM-CAD Open Source Solutions
#    Copyright (C) 2011-2019 https://OmniaSolutions.website
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this prograIf not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
'''
Created on Sep 7, 2019

@author: mboscolo
'''
from odoo import models
from odoo import fields
from odoo import api
from odoo.exceptions import UserError
import requests


class PlmConvertServers(models.Model):
    _name = "plm.convert.servers"
    _description = "Servers of conversions"
    _order = 'sequence ASC'

    sequence = fields.Integer('Sequence')
    name = fields.Char('Server Name')
    address = fields.Char('Server IP Address')
    protocol = fields.Char('Server Protocol', default='http')
    port = fields.Char('Server Port')
    proc_to_kill = fields.Char('Process To Kill')
    client_processes = fields.Text('Client Processes')

    def getBaseUrl(self):
        for server in self:
            return '%s://%s:%s' % (server.protocol, server.address, server.port)
        return ''

    def getMainServer(self):
        return self.search([], order='sequence ASC', limit=1)

    @api.model
    def create(self, vals):
        ret = super(PlmConvertServers, self).create(vals)
        if not vals.get('sequence'):
            ret.sequence = ret.id
        return ret

    def testConnection(self):
        for server in self:
            base_url = server.getBaseUrl()
            url = base_url + '/odooplm/api/v1.0/isalive'
            try:
                response = requests.get(url)
            except Exception as ex:
                raise UserError("Server not correctly defined. Error %r" % (ex))
            if response.status_code != 200:
                raise UserError("Server not correctly defined")
            if response.text != 'OK':
                raise UserError("Server not correctly defined")
        title = "Connection Test Succeeded!"
        message = "Everything seems properly set up!"
        return self.infoMessage(title, message)

    def infoMessage(self, title, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'sticky': False,
            }
        }

    def killProcess(self):
        for server in self:
            if server.proc_to_kill:
                base_url = server.getBaseUrl()
                url = base_url + '/odooplm/api/v1.0/kill_process'
                params = {}
                params['pid'] = server.proc_to_kill
                try:
                    response = requests.post(url, params=params)
                except Exception as ex:
                    raise UserError('Cannot kill process due to error %r' % (ex))
                if response.status_code != 200:
                    raise UserError('Cannot kill process %r' % (response.status_code))
        title = "Process Killed Succeeded!"
        message = "Everything went ok!"
        server.client_processes = ''
        return self.infoMessage(title, message)

    def getClientProcesses(self):
        for server in self:
            base_url = server.getBaseUrl()
            url = base_url + '/odooplm/api/v1.0/get_processes_details'
            try:
                response = requests.get(url)
            except Exception as ex:
                raise UserError("Cannot get process list. Error %r" % (ex))
            if response.status_code != 200:
                raise UserError("Wrong responce from server %r" % (response.status_code))
            res = response.json()
            outMsg = ''
            for procId, procVals in res.items():
                outMsg += 'Proc ID %r\n' % (procId)
                outMsg += '    Name %r\n' % (procVals.get('name', ''))
                outMsg += '    Exe %r\n' % (procVals.get('exe', ''))
                outMsg += '    Working Dir %r\n\n' % (procVals.get('directory', ''))
            server.client_processes = outMsg
