# -*- encoding: utf-8 -*-
##############################################################################
#
#    OmniaSolutions, Your own solutions
#    Copyright (C) 2010 OmniaSolutions (<http://omniasolutions.eu>). All Rights Reserved
#    $Id$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
import random
import string
import base64
import os
import time
from datetime import datetime
from openerp.osv.orm import except_orm
import openerp.tools as tools
from openerp.exceptions import UserError
from openerp.osv import fields as oldFields
from openerp import models
from openerp import fields
from openerp import api
from openerp import _
import logging
_logger = logging.getLogger(__name__)


# To be adequated to plm.component class states
USED_STATES = [('draft', _('Draft')),
               ('confirmed', _('Confirmed')),
               ('released', _('Released')),
               ('undermodify', _('UnderModify')),
               ('obsoleted', _('Obsoleted'))]
USEDIC_STATES = dict(USED_STATES)


def random_name():
    random.seed()
    d = [random.choice(string.ascii_letters) for _x in xrange(20)]
    return ("".join(d))


def create_directory(path):
    dir_name = random_name()
    path = os.path.join(path, dir_name)
    os.makedirs(path)
    return dir_name


class plm_document(models.Model):
    _name = 'plm.document'
    _table = 'plm_document'
    _inherit = ['mail.thread', 'ir.attachment']

    @api.model
    def get_checkout_user(self, oid):
        lastDoc = self._getlastrev([oid])
        if lastDoc:
            for docBrws in self.env['plm.checkout'].search([('documentid', '=', lastDoc[0])]):
                return docBrws.userid
        return False

    @api.model
    def _is_checkedout_for_me(self, oid):
        """
            Get if given document (or its latest revision) is checked-out for the requesting user
        """
        userBrws = self.get_checkout_user(oid)
        if userBrws:
            if userBrws.id == self.env.uid:
                return True
        return False

    @api.multi
    def _getlastrev(self):
        result = []
        for objDoc in self:
            docIds = self.search([('name', '=', objDoc.name)], order='revisionid').ids
            docIds.sort()   # Ids are not surely ordered, but revision are always in creation order.
            if docIds:
                result.append(docIds[len(docIds) - 1])
            else:
                logging.warning('[_getlastrev] No documents are found for object with name: "%s"' % (objDoc.name))
        return list(set(result))

    @api.multi
    def GetLastNamesFromID(self):
        """
            get the last rev
        """
        newIds = self._getlastrev(ids=self.env.ids)
        return self.read(newIds, ['datas_fname'])

    @api.multi
    def _data_get_files(self, listedFiles=([], []), forceFlag=False):
        """
            Get Files to return to Client
        """
        result = []
        datefiles, listfiles = listedFiles
        for objDoc in self:
            if objDoc.type == 'binary':
                timeDoc = self.getLastTime(objDoc.id)
                timeSaved = time.mktime(timeDoc.timetuple())
                try:
                    isCheckedOutToMe = self._is_checkedout_for_me(objDoc.id)
                    if not(objDoc.datas_fname in listfiles):
                        if (not objDoc.store_fname) and (objDoc.db_datas):
                            value = objDoc.db_datas
                        else:
                            value = file(os.path.join(self._get_filestore(self.env.cr), objDoc.store_fname), 'rb').read()
                        result.append((objDoc.id, objDoc.datas_fname, base64.encodestring(value), isCheckedOutToMe, timeDoc))
                    else:
                        if forceFlag:
                            isNewer = True
                        else:
                            timefile = time.mktime(datetime.strptime(str(datefiles[listfiles.index(objDoc.datas_fname)]), '%Y-%m-%d %H:%M:%S').timetuple())
                            isNewer = (timeSaved - timefile) > 5
                        if (isNewer and not(isCheckedOutToMe)):
                            if (not objDoc.store_fname) and (objDoc.db_datas):
                                value = objDoc.db_datas
                            else:
                                value = file(os.path.join(self._get_filestore(self.env.cr), objDoc.store_fname), 'rb').read()
                            result.append((objDoc.id, objDoc.datas_fname, base64.encodestring(value), isCheckedOutToMe, timeDoc))
                        else:
                            result.append((objDoc.id, objDoc.datas_fname, False, isCheckedOutToMe, timeDoc))
                except Exception, ex:
                    logging.error("_data_get_files : Unable to access to document (" + str(objDoc.name) + "). Error :" + str(ex))
                    result.append((objDoc.id, objDoc.datas_fname, False, True, self.getServerTime()))
        return result

    @api.multi
    def _data_get(self, name, arg):
        result = {}
        value = False
        for objDoc in self:
            if objDoc.type == 'binary':
                if not objDoc.store_fname:
                    value = objDoc.db_datas
                    if not value or len(value) < 1:
                        raise UserError(_("Document %s - %s cannot be accessed" % (str(objDoc.name), str(objDoc.revisionid))))
                else:
                    filestore = os.path.join(self._get_filestore(self.env.cr), objDoc.store_fname)
                    if os.path.exists(filestore):
                        value = file(filestore, 'rb').read()
                if value and len(value) > 0:
                    result[objDoc.id] = base64.encodestring(value)
                else:
                    result[objDoc.id] = ''
        return result

    @api.multi
    def _data_set(self, name, value, args=None):
        if self.type == 'binary':
            if not value:
                filename = self.store_fname
                try:
                    os.unlink(os.path.join(self._get_filestore(self.env.cr), filename))
                except:
                    pass
                self.env.cr.execute('update plm_document set store_fname=NULL WHERE id=%s', (self.id))
                return True
            try:
                printout = False
                preview = False
                if self.printout:
                    printout = self.printout
                if self.preview:
                    preview = self.preview
                db_datas = b''                    # Clean storage field.
                fname, filesize = self._manageFile(binvalue=value)
                self.env.cr.execute('update plm_document set store_fname=%s,file_size=%s,db_datas=%s where id=%s', (fname, filesize, db_datas, self.id))
                self.env['plm.backupdoc'].create({'userid': self.env.uid,
                                                  'existingfile': fname,
                                                  'documentid': self.env.oid,
                                                  'printout': printout,
                                                  'preview': preview
                                                  })

                return True
            except Exception, ex:
                raise except_orm(_('Error in _data_set'), str(ex))
        else:
            return True

    @api.model
    def _explodedocs(self, oid, kinds, listed_documents=[], recursion=True):
        result = []
        documentRelation = self.env['plm.document.relation']

        def getAllDocumentChildId(fromID, kinds):
            docRelBrwsList = documentRelation.search([('parent_id', '=', fromID), ('link_kind', 'in', kinds)])
            for child in docRelBrwsList:
                idToAdd = child.child_id.id
                if idToAdd not in result:
                    result.append(idToAdd)
                    if recursion:
                        getAllDocumentChildId(idToAdd, kinds)
        getAllDocumentChildId(oid, kinds)
        return result

    @api.model
    def _relateddocs(self, oid, kinds, listed_documents=[], recursion=True):
        result = []
        if (oid in listed_documents):
            return result
        documentRelation = self.env['plm.document.relation']
        docBrwsList = documentRelation.search([('child_id', '=', oid), ('link_kind', 'in', kinds)])
        if len(docBrwsList) == 0:
            return []
        for child in docBrwsList:
            if recursion:
                listed_documents.append(oid)
                result.extend(self._relateddocs(child.parent_id.id, kinds, listed_documents, recursion))
            if child.parent_id:
                result.append(child.parent_id.id)
        return list(set(result))

    @api.model
    def _relatedbydocs(self, oid, kinds, listed_documents=[], recursion=True):
        result = []
        if (oid in listed_documents):
            return result
        documentRelation = self.env['plm.document.relation']
        docBrwsList = documentRelation.search([('parent_id', '=', oid), ('link_kind', 'in', kinds)])
        if len(docBrwsList) == 0:
            return []
        for child in docBrwsList:
            if recursion:
                listed_documents.append(oid)
                result.extend(self._relatedbydocs(child.child_id.id, kinds, listed_documents, recursion))
            if child.child_id.id:
                result.append(child.child_id.id)
        return list(set(result))

    @api.multi
    def _data_check_files(self, listedFiles=(), forceFlag=False):
        result = []
        datefiles, listfiles = listedFiles
        for objDoc in self:
            if objDoc.type == 'binary':
                checkOutUser = ''
                isCheckedOutToMe = False
                timeDoc = self.getLastTime(objDoc.id)
                timeSaved = time.mktime(timeDoc.timetuple())
                checkoutUserBrws = self.get_checkout_user(objDoc.id, context=None)
                if checkoutUserBrws:
                    checkOutUser = checkoutUserBrws.name
                    if checkoutUserBrws.id == self.env.uid:
                        isCheckedOutToMe = True
                if (objDoc.datas_fname in listfiles):
                    if forceFlag:
                        isNewer = True
                    else:
                        listFileIndex = listfiles.index(objDoc.datas_fname)
                        timefile = time.mktime(datetime.strptime(str(datefiles[listFileIndex]), '%Y-%m-%d %H:%M:%S').timetuple())
                        isNewer = (timeSaved - timefile) > 5
                    collectable = isNewer and not(isCheckedOutToMe)
                else:
                    collectable = True
                objDatas = False
                try:
                    objDatas = objDoc.datas
                except Exception, ex:
                    logging.error('Document with "id": %s  and "name": %s may contains no data!!         Exception: %s' % (objDoc.id, objDoc.name, ex))
                if (objDoc.file_size < 1) and (objDatas):
                    file_size = len(objDoc.datas)
                else:
                    file_size = objDoc.file_size
                result.append((objDoc.id, objDoc.datas_fname, file_size, collectable, isCheckedOutToMe, checkOutUser))
        return list(set(result))

    @api.multi
    def copy(self, defaults={}):
        """
            Overwrite the default copy method
        """
        documentRelation = self.env['plm.document.relation']
        docBrwsList = documentRelation.search([('parent_id', '=', self.env.id)])
        previous_name = self.name
        if 'name' not in defaults:
            new_name = 'Copy of %s' % previous_name
            l = self.search([('name', '=', new_name)], order='revisionid')
            if len(l) > 0:
                new_name = '%s (%s)' % (new_name, len(l) + 1)
            defaults['name'] = new_name
        fname, filesize = self._manageFile(self.id)
        defaults['store_fname'] = fname
        defaults['file_size'] = filesize
        defaults['state'] = 'draft'
        defaults['writable'] = True
        newID = super(plm_document, self).copy(defaults)
        if (newID):
            self.wf_message_post([newID], body=_('Copied starting from : %s.' % previous_name))
        for brwEnt in docBrwsList:
            documentRelation.create({
                                    'parent_id': newID,
                                    'child_id': brwEnt.child_id.id,
                                    'configuration': brwEnt.configuration,
                                    'link_kind': brwEnt.link_kind,
                                    })
        return newID

    @api.model
    def _manageFile(self, oid, binvalue=None):
        """
            use given 'binvalue' to save it on physical repository and to read size (in bytes).
        """
        path = self._get_filestore(self.env.cr)
        if not os.path.isdir(path):
            try:
                os.makedirs(path)
            except:
                raise UserError(_("Permission denied or directory %s cannot be created." % (str(path))))
        flag = None
        # This can be improved
        for dirs in os.listdir(path):
            if os.path.isdir(os.path.join(path, dirs)) and len(os.listdir(os.path.join(path, dirs))) < 4000:
                flag = dirs
                break
        if binvalue is None:
            fileStream = self._data_get([oid], name=None, arg=None)
            binvalue = fileStream[fileStream.keys()[0]]

        flag = flag or create_directory(path)
        filename = random_name()
        fname = os.path.join(path, flag, filename)
        fobj = file(fname, 'wb')
        value = base64.decodestring(binvalue)
        fobj.write(value)
        fobj.close()
        return (os.path.join(flag, filename), len(value))

    @api.model
    def _iswritable(self, oid):
        checkState = ('draft')
        if not oid.type == 'binary':
            logging.warning("_iswritable : Part (" + str(oid.engineering_code) + "-" + str(oid.engineering_revision) + ") not writable as hyperlink.")
            return False
        if not oid.engineering_writable:
            logging.warning("_iswritable : Part (" + str(oid.engineering_code) + "-" + str(oid.engineering_revision) + ") not writable.")
            return False
        if oid.state not in checkState:
            logging.warning("_iswritable : Part (" + str(oid.engineering_code) + "-" + str(oid.engineering_revision) + ") in status ; " + str(oid.state) + ".")
            return False
        if not oid.engineering_code:
            logging.warning("_iswritable : Part (" + str(oid.name) + "-" + str(oid.engineering_revision) + ") without Engineering P/N.")
            return False
        return True

    @api.multi
    def newVersion(self):
        """
            create a new version of the document (to WorkFlow calling)
        """
        if self.NewRevision() is not None:
            return True
        return False

    @api.multi
    def NewRevision(self):
        """
            create a new revision of the document
        """
        newID = None
        for tmpObject in self:
            latestIDs = self.GetLatestIds([(tmpObject.name, tmpObject.revisionid, False)])
            for oldObject in self.browse(latestIDs):
                oldObject.write({'state': 'undermodify'}, check=False)
                defaults = {}
                defaults['name'] = oldObject.name
                defaults['revisionid'] = int(oldObject.revisionid) + 1
                defaults['writable'] = True
                defaults['state'] = 'draft'
                newID = super(plm_document, self).copy(oldObject.id, defaults)
                self.wf_message_post([oldObject.id], body=_('Created : New Revision.'))
                break
            break
        return (newID, defaults['revisionid'])

    @api.multi
    def Clone(self, defaults={}):
        """
            create a new copy of the document
        """
        defaults = {}
        exitValues = {}
        newID = self.copy(defaults)
        if newID is not None:
            newEnt = self.browse(newID)
            exitValues['_id'] = newID
            exitValues['name'] = newEnt.name
            exitValues['revisionid'] = newEnt.revisionid
        return exitValues

    @api.model
    def CheckSaveUpdate(self, documents, default=None):
        """
            Save or Update Documents
        """
        retValues = []
        for document in documents:
            hasSaved = False
            if not ('name' in document) or ('revisionid' not in document):
                document['documentID'] = False
                document['hasSaved'] = hasSaved
                continue
            docBrwsList = self.search([('name', '=', document['name']),
                                      ('revisionid', '=', document['revisionid'])],
                                      order='revisionid')
            if not docBrwsList:
                hasSaved = True
            else:
                existingID = docBrwsList[0].id
                if self.getLastTime(existingID) < datetime.strptime(str(document['lastupdate']), '%Y-%m-%d %H:%M:%S'):
                    if docBrwsList[0].writable:
                        hasSaved = True
            document['documentID'] = existingID
            document['hasSaved'] = hasSaved
            retValues.append(document)
        return retValues

    @api.model
    def SaveOrUpdate(self, documents, default=None):
        """
            Save or Update Documents
        """
        retValues = []
        for document in documents:
            hasSaved = False
            hasUpdated = False
            if not ('name' in document) or ('revisionid' not in document):
                document['documentID'] = False
                document['hasSaved'] = hasSaved
                document['hasUpdated'] = hasUpdated
                continue
            docBrwsList = self.search([('name', '=', document['name']), ('revisionid', '=', document['revisionid'])], order='revisionid')
            if not docBrwsList:
                existingID = self.create(document).id
                hasSaved = True
            else:
                existingID = docBrwsList[0].id
#                logging.info("SaveOrUpdate : time db : %s time file : %s" %(str(self.getLastTime(cr,uid,existingID).strftime('%Y-%m-%d %H:%M:%S')), str(document['lastupdate'])))
                if self.getLastTime(existingID) < datetime.strptime(str(document['lastupdate']), '%Y-%m-%d %H:%M:%S'):
                    if self._iswritable(docBrwsList[0]):
                        del(document['lastupdate'])
                        if not self.browse([existingID]).write(document, check=True):
                            raise UserError(_("Document %s  -  %s cannot be updated" % (str(document['name']), str(document['revisionid']))))
                        hasSaved = True
            document['documentID'] = existingID
            document['hasSaved'] = hasSaved
            document['hasUpdated'] = hasUpdated
            retValues.append(document)
        return retValues

    @api.model
    def RegMessage(self, request, default=None):
        """
            Registers a message for requested document
        """
        oid, message = request
        self.wf_message_post([oid], body=_(message))
        return False

    @api.model
    def UpdateDocuments(self, documents, default=None):
        """
            Save or Update Documents
        """
        ret = True
        for document in documents:
            oid = document['documentID']
            del(document['documentID'])
            ret = ret and self.browse([oid]).write(document, check=True)
        return ret

    @api.multi
    def CleanUp(self, default=None):
        """
            Remove faked documents
        """
        self.env.cr.execute("delete from plm_document where store_fname=NULL and type='binary'")
        return True

    @api.model
    def QueryLast(self, request=([], []), default=None):
        """
            Query to return values based on columns selected.
        """
        expData = []
        queryFilter, columns = request
        if len(columns) < 1:
            return expData
        if 'revisionid' in queryFilter:
            del queryFilter['revisionid']
        docBrwsList = self.search(queryFilter, order='revisionid').ids
        if len(docBrwsList) > 0:
            allIDs = docBrwsList.ids
            allIDs.sort()
            tmpData = self.export_data(allIDs, columns)
            if 'datas' in tmpData:
                expData = tmpData['datas']
        return expData

    @api.multi
    def ischecked_in(self):
        """
            Check if a document is checked-in
        """
        checkoutType = self.env['plm.checkout']
        for document in self:
            if checkoutType.search([('documentid', '=', document.id)]):
                logging.warning(_("The document %s - %s has not checked-in" % (str(document.name), str(document.revisionid))))
                return False
        return True

    @api.multi
    def wf_message_post(self, body=''):
        """
            Writing messages to follower, on multiple objects
        """
        if body:
            self.message_post(body=_(body))

    @api.multi
    def setCheckContextWrite(self, checkVal=True):
        '''
            :checkVal Set check flag in context to do state verification in component write
        '''
        localCtx = self.env.context.copy()
        localCtx['check'] = checkVal
        self.env.context = localCtx

    @api.multi
    def commonWFAction(self, writable, state, check):
        '''
            :writable set writable flag for component
            :state define new product state
            :check do state verification in component write
        '''
        self.setCheckContextWrite(check)
        objId = self.write({'writable': writable,
                            'state': state
                            })
        if objId:
            self.wf_message_post(body=_('Status moved to: %s.' % (USEDIC_STATES[state])))
        return objId

    @api.multi
    def action_draft(self):
        """
            action to be executed for Draft state
        """
        return self.commonWFAction(True, 'draft', False)

    @api.multi
    def action_confirm(self):
        """
            action to be executed for Confirm state
        """
        return self.commonWFAction(False, 'confirmed', False)

    @api.multi
    def action_release(self):
        """
            release the object
        """
        for oldObject in self:
            lastDocBrws = self._getbyrevision(oldObject.name, oldObject.revisionid - 1)
            if lastDocBrws:
                lastDocBrws.commonWFAction(False, 'released', False)
        if self.ischecked_in():
            return self.commonWFAction(False, 'released', False)
        return False

    @api.multi
    def action_obsolete(self):
        """
            obsolete the object
        """
        return self.commonWFAction(False, 'obsoleted', False)

    @api.multi
    def action_reactivate(self):
        """
            reactivate the object
        """
        defaults = {}
        defaults['engineering_writable'] = False
        defaults['state'] = 'released'
        if self.ischecked_in():
            self.setCheckContextWrite(False)
            objId = self.write(defaults)
            if objId:
                self.wf_message_post(body=_('Status moved to:%s.' % (USEDIC_STATES[defaults['state']])))
            return objId
        return False

    @api.multi
    def blindwrite(self, vals):
        """
            blind write for xml-rpc call for recovering porpouse
            DO NOT USE FOR COMMON USE !!!!
        """
        return self.write(vals, check=False)

#   Overridden methods for this entity
    def _get_filestore(self, cr):
        dms_Root_Path = tools.config.get('document_path', os.path.join(tools.config['root_path'], 'filestore'))
        return os.path.join(dms_Root_Path, cr.dbname)

    @api.multi
    def write(self, vals):
        checkState = ('confirmed', 'released', 'undermodify', 'obsoleted')
        check = self.env.context.get('check', True)
        if check:
            for customObject in self:
                if customObject.state in checkState:
                    raise UserError(_("The active state does not allow you to make save action"))
                    return False
        return super(plm_document, self).write(vals)

    @api.multi
    def unlink(self):
        values = {'state': 'released', }
        checkState = ('undermodify', 'obsoleted')
        for checkObj in self:
            docBrwsList = self.search([('name', '=', checkObj.name), ('revisionid', '=', checkObj.revisionid - 1)])
            if len(docBrwsList) > 0:
                oldObject = docBrwsList[0]
                if oldObject.state in checkState:
                    self.wf_message_post([oldObject.id], body=_('Removed : Latest Revision.'))
                    if not oldObject.write(values, check=False):
                        logging.warning("unlink : Unable to update state to old document (" + str(oldObject.name) + "-" + str(oldObject.revisionid) + ").")
                        return False
        return super(plm_document, self).unlink()

#   Overridden methods for this entity
    @api.model
    def _check_duplication(self, vals, ids=None, op='create'):
        SUPERUSER_ID = 1
        name = vals.get('name', False)
        parent_id = vals.get('parent_id', False)
        ressource_parent_type_id = vals.get('ressource_parent_type_id', False)
        ressource_id = vals.get('ressource_id', 0)
        revisionid = vals.get('revisionid', 0)
        if op == 'write':
            for directory in self.browse(ids):
                if not name:
                    name = directory.name
                if not parent_id:
                    parent_id = directory.parent_id and directory.parent_id.id or False
                # TODO fix algo
                if not ressource_parent_type_id:
                    ressource_parent_type_id = directory.ressource_parent_type_id and directory.ressource_parent_type_id.id or False
                if not ressource_id:
                    ressource_id = directory.ressource_id and directory.ressource_id or 0
                docBrwsList = self.search([('id', '<>', directory.id),
                                           ('name', '=', name),
                                           ('parent_id', '=', parent_id),
                                           ('ressource_parent_type_id', '=', ressource_parent_type_id),
                                           ('ressource_id', '=', ressource_id),
                                           ('revisionid', '=', revisionid)])
                if docBrwsList:
                    return False
        if op == 'create':
            docBrwsList = self.search(SUPERUSER_ID,
                              [('name', '=', name),
                               ('parent_id', '=', parent_id),
                               ('ressource_parent_type_id', '=', ressource_parent_type_id),
                               ('ressource_id', '=', ressource_id),
                               ('revisionid', '=', revisionid)])
            if docBrwsList:
                return False
        return True
#   Overridden methods for this entity

    @api.one
    def _get_checkout_state(self):
        chechRes = self.getCheckedOut(self.id, None)
        if chechRes:
            self.checkout_user = str(chechRes[2])
        else:
            self.checkout_user = ''

    @api.one
    def _is_checkout(self):
        chechRes = self.getCheckedOut(self.id, None)
        if chechRes:
            self.is_checkout = True
        else:
            self.is_checkout = False

    usedforspare = fields.Boolean(_('Used for Spare'),
                                  help=_("Drawings marked here will be used printing Spare Part Manual report."))
    revisionid = fields.Integer(_('Revision Index'),
                                required=True)
    writable = fields.Boolean(_('Writable'))
    printout = fields.Binary(_('Printout Content'),
                             help=_("Print PDF content."))
    preview = fields.Binary(_('Preview Content'),
                            help=_("Static preview."))
    state = fields.Selection(USED_STATES,
                             _('Status'),
                             help=_("The status of the product."),
                             readonly="True",
                             required=True)
    checkout_user = fields.Char(string=_("Checked-Out to"),
                                compute=_get_checkout_state)
    is_checkout = fields.Boolean(_('Is Checked-Out'),
                                 compute=_is_checkout,
                                 store=False)
    linkedcomponents = fields.Many2many('product.product',
                                        'plm_component_document_rel',
                                        'document_id',
                                        'component_id',
                                        _('Linked Parts'))

    _columns = {'datas': oldFields.function(_data_get, method=True, fnct_inv=_data_set, string=_('File Content'), type="binary"),
                }
    _defaults = {'usedforspare': lambda *a: False,
                 'revisionid': lambda *a: 0,
                 'writable': lambda *a: True,
                 'state': lambda *a: 'draft',
                 'res_id': lambda *a: False,
                 }

    _sql_constraints = [
        ('name_unique', 'unique (name, revisionid)', 'File name has to be unique!')  # qui abbiamo la sicurezza dell'univocita del nome file
    ]

    @api.model
    def CheckedIn(self, files, default=None):
        """
            Get checked status for requested files
        """
        retValues = []

        def getcheckedfiles(files):
            res = []
            for fileName in files:
                plmDocList = self.search([('datas_fname', '=', fileName)], order='revisionid')
                if len(plmDocList) > 0:
                    ids = plmDocList.ids
                    ids.sort()
                    res.append([fileName, not (self._is_checkedout_for_me(ids[len(ids) - 1]))])
            return res

        if len(files) > 0:  # no files to process
            retValues = getcheckedfiles(files)
        return retValues

    @api.model
    def GetUpdated(self, vals):
        """
            Get Last/Requested revision of given items (by name, revision, update time)
        """
        docData, attribNames = vals
        ids = self.GetLatestIds(docData)
        return self.read(list(set(ids)), attribNames)

    @api.model
    def GetLatestIds(self, vals, forceCADProperties=False):
        """
            Get Last/Requested revision of given items (by name, revision, update time)
        """
        ids = []

        def getCompIds(docName, docRev):
            if docRev is None or docRev is False:
                docBrwsList = self.search([('name', '=', docName)], order='revisionid')
                if len(docBrwsList) > 0:
                    ids.append(docBrwsList.ids[-1])
            else:
                ids.extend(self.search([('name', '=', docName), ('revisionid', '=', docRev)]).ids)

        for docName, docRev, docIdToOpen in vals:
            checkOutUser = self.get_checkout_user(docIdToOpen)
            if checkOutUser:
                isMyDocument = self.isCheckedOutByMe(docIdToOpen)
                if isMyDocument:
                    return []    # Document properties will be not updated
                else:
                    getCompIds(docName, docRev)
            else:
                getCompIds(docName, docRev)
        return list(set(ids))

    @api.multi
    def isCheckedOutByMe(self):
        checkoutBrwsList = self.env['plm.checkout'].search([('documentid', '=', self.id), ('userid', '=', self.env.uid)])
        for checkoutBrws in checkoutBrwsList:
            return checkoutBrws.id
        return None

    @api.model
    def CheckAllFiles(self, request, default=None):
        """
            Evaluate documents to return
        """
        forceFlag = False
        listed_models = []
        listed_documents = []
        outIds = []
        oid, listedFiles, selection = request
        outIds.append(oid)
        if selection is False:
            selection = 1   # Case of selected
        if selection < 0:   # Case of force refresh PWS
            forceFlag = True
            selection = selection * (-1)
        # Get relations due to layout connected
        docArray = self._relateddocs(oid, ['LyTree'], listed_documents)
        # Get Hierarchical tree relations due to children
        modArray = self._explodedocs(oid, ['HiTree'], listed_models)
        outIds = list(set(outIds + modArray + docArray))
        if selection == 2:  # Case of latest
            outIds = self._getlastrev(outIds)
        return self._data_check_files(outIds, listedFiles, forceFlag)

    @api.model
    def CheckInRecursive(self, request, default=None):
        """
            Evaluate documents to return
        """
        def getDocId(args):
            docName = args.get('name')
            docRev = args.get('revisionid')
            docBrwsList = self.search([('name', '=', docName), ('revisionid', '=', docRev)])
            if not docBrwsList:
                logging.warning('Document with name "%s" and revision "%s" not found' % (docName, docRev))
                return False
            return docBrwsList[0].id

        oid, _listedFiles, selection = request
        oid = getDocId(oid)
        checkRes = self.isCheckedOutByMe(oid)
        if not checkRes:
            return False
        if selection is False:
            selection = 1
        if selection < 0:
            selection = selection * (-1)
        documentRelation = self.pool.get('plm.document.relation')
        docArray = []

        def recursionCompute(oid):
            if oid in docArray:
                return
            else:
                docArray.append(oid)
            docBrwsList = documentRelation.search(['|', ('parent_id', '=', oid), ('child_id', '=', oid)])
            for objRel in docBrwsList:
                if objRel.link_kind in ['LyTree', 'RfTree'] and objRel.child_id.id not in docArray:
                    docArray.append(objRel.child_id.id)
                else:
                    if objRel.parent_id.id == oid:
                        recursionCompute(objRel.child_id.id)

        recursionCompute(oid)
        if selection == 2:
            docArray = self._getlastrev(docArray)
        checkoutObj = self.pool.get('plm.checkout')
        for docId in docArray:
            checkOutBrwsList = checkoutObj.search([('documentid', '=', docId), ('userid', '=', self.env.uid)])
            checkOutBrwsList.unlink()
        return self.read(docArray, ['datas_fname'])

    @api.model
    def GetSomeFiles(self, request, default=None):
        """
            Extract documents to be returned
        """
        forceFlag = False
        ids, listedFiles, selection = request
        if not selection:
            selection = 1

        if selection < 0:
            forceFlag = True
            selection = selection * (-1)

        if selection == 2:
            docArray = self._getlastrev()
        else:
            docArray = ids
        return self._data_get_files(docArray, listedFiles, forceFlag)

    @api.model
    def GetAllFiles(self, request, default=None):
        """
            Extract documents to be returned
        """
        forceFlag = False
        listed_models = []
        listed_documents = []
        modArray = []
        oid, listedFiles, selection = request
        if not selection:
            selection = 1

        if selection < 0:
            forceFlag = True
            selection = selection * -1

        kind = 'HiTree'                   # Get Hierarchical tree relations due to children
        docArray = self._explodedocs(oid, [kind], listed_models)
        if oid not in docArray:
            docArray.append(oid)        # Add requested document to package
        for item in docArray:
            kinds = ['LyTree', 'RfTree']               # Get relations due to layout connected
            modArray.extend(self._relateddocs(item, kinds, listed_documents))
            modArray.extend(self._explodedocs(item, kinds, listed_documents))
#             kind='RfTree'               # Get relations due to referred connected
#             modArray.extend(self._relateddocs(cr, uid, item, kind, listed_documents))
#             modArray.extend(self._explodedocs(cr, uid, item, kind, listed_documents))
        modArray.extend(docArray)
        docArray = list(set(modArray))    # Get unique documents object IDs
        if selection == 2:
            docArray = self._getlastrev(docArray)
        if oid not in docArray:
            docArray.append(oid)     # Add requested document to package
        return self._data_get_files(docArray, listedFiles, forceFlag)

    @api.multi
    def GetRelatedDocs(self, default=None):
        """
            Extract documents related to current one(s) (layouts, referred models, etc.)
        """
        related_documents = []
        listed_documents = []
        read_docs = []
        for oid in self.ids:
            kinds = ['RfTree', 'LyTree']   # Get relations due to referred models
            read_docs.extend(self._relateddocs(oid, kinds, listed_documents, False))
            read_docs.extend(self._relatedbydocs(oid, kinds, listed_documents, False))
        documents = self.browse(read_docs)
        for document in documents:
            related_documents.append([document.id, document.name, document.preview])
        return related_documents

    @api.multi
    def getServerTime(self):
        """
            calculate the server db time
        """
        return datetime.now()

    @api.model
    def getLastTime(self, oid, default=None):
        """
            get document last modification time
        """
        obj = self.browse(oid)
        if(obj.write_date is not False):
            return datetime.strptime(obj.write_date, '%Y-%m-%d %H:%M:%S')
        else:
            return datetime.strptime(obj.create_date, '%Y-%m-%d %H:%M:%S')

    @api.multi
    def getUserSign(self, userId):
        """
            get the user name
        """
        userType = self.env['res.users']
        uiUser = userType.browse(userId)
        return uiUser.name

    @api.multi
    def _getbyrevision(self, name, revision):
        result = False
        for result in self.search([('name', '=', name), ('revisionid', '=', revision)]):
            return result
        return result

    @api.model
    def getCheckedOut(self, oid, default=None):
        checkoutType = self.env['plm.checkout']
        checkoutBrwsList = checkoutType.search([('documentid', '=', oid)])
        for checkOutBrws in checkoutBrwsList:
            return(checkOutBrws.documentid.name,
                   checkOutBrws.documentid.revisionid,
                   self.getUserSign(checkOutBrws.userid.id),
                   checkOutBrws.hostname)
        return False

    @api.model
    def _file_delete(self, fname):
        '''
            Delete file only if is not saved on plm.backupdoc
        '''
        backupDocBrwsList = self.env['plm.backupdoc'].search([('existingfile', '=', fname)])
        if not backupDocBrwsList:
            return super(plm_document, self)._file_delete(fname)

    @api.model
    def GetNextDocumentName(self, documentName):
        '''
            Return a new name due to sequence next number.
        '''
        nextDocNum = self.env['ir.sequence'].next_by_code('plm.document.progress')
        return documentName + '-' + nextDocNum

plm_document()
