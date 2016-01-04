import os
import logging
from django.conf import settings
import json
import urllib2
import base64
import requests
logger = logging.getLogger(__name__)
import sys


def create_patient_record(individual_id,project_id,patient_details=None):
  '''
    Make a patient record:
  
    Create a patient record in phenotips.
    By convention username and password are project_id,project_idproject_id
    Authentication is protected by access to machine/localhost  
  
  '''
  uri = settings.PHENOPTIPS_HOST_NAME + '/bin/PhenoTips/OpenPatientRecord?create=true&eid=' + individual_id
  if patient_details is not None:
    uri += '&gender='+patient_details['gender']
  uname,pwd = get_uname_pwd_for_project(project_id)
  result=do_authenticated_call_to_phenotips(uri,uname,pwd)
  if result is not None and result.getcode()==200:
      print 'successfully created or updated patient',individual_id
      patient_eid = convert_internal_id_to_external_id(individual_id,uname,pwd)
      collaborator_username,collab_pwd=get_uname_pwd_for_project(project_id,read_only=True)
      add_read_only_user_to_phenotips_patient(collaborator_username,patient_eid)
  else:
      print 'error creating patient',individual_id,':',result
  
      

def do_authenticated_call_to_phenotips(url,uname,pwd):
  '''
    Authenticates to phenotips, fetches (GET) given results and returns that
  '''
  try:
    password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
    request = urllib2.Request(url)
    base64string = base64.encodestring('%s:%s' % (uname, pwd)).replace('\n', '')
    request.add_header("Authorization", "Basic %s" % base64string)   
    result = urllib2.urlopen(request)   
    return result
  except Exception as e:
    raise


def convert_internal_id_to_external_id(int_id,project_phenotips_uname,project_phenotips_pwd):
  '''
    To help process a translation of internal id to external id 
  '''
  try:
    url= os.path.join(settings.PHENOPTIPS_HOST_NAME,'rest/patients/eid/'+str(int_id))   
    result = do_authenticated_call_to_phenotips(url,project_phenotips_uname,project_phenotips_pwd)
    as_json = json.loads(result.read())
    return as_json['id']
  except Exception as e:
    print 'convert internal id error:',e
    logger.error('phenotips.views:'+str(e))
    raise
  

def get_uname_pwd_for_project(project_name,read_only=False):
  '''
    Return the username and password for this project. 
    If read_only flag is true, only a read-only username will be returned
  '''
  pwd=project_name+project_name
  if not read_only:
    uname=project_name
    return uname,pwd
  uname=project_name+ '_view'
  return uname,pwd



def get_names_for_user(project_name,read_only=False):
  '''
    Returns the first and last name and password to be allocated for this project. 
    If read_only flag is true, the read-only equivalent is returned
  
    Returns a tuple: (first_name,last_name)
  '''
  #keeping last name empty for now, variable is mainly a place holder for the future
  last_name=''
  if not read_only:
    first_name=project_name
    return (first_name,last_name)
  first_name=project_name+ ' (view only)'
  return (first_name,last_name)


def add_new_user_to_phenotips(new_user_first_name, new_user_last_name,new_user_name,email_address,new_user_pwd):
  '''
    TBD: we need to put this password in a non-checkin file:
    Generates a new user in phenotips
  '''
  admin_uname=settings.PHENOTIPS_ADMIN_UNAME
  admin_pwd=settings.PHENOTIPS_ADMIN_PWD
  headers={"Content-Type": "application/x-www-form-urlencoded"}
  data={'parent':'XWiki.XWikiUsers'}
  url = settings.PHENOPTIPS_HOST_NAME + '/rest/wikis/xwiki/spaces/XWiki/pages/' + new_user_name
  do_authenticated_PUT(admin_uname,admin_pwd,url,data,headers) 
  data={'className':'XWiki.XWikiUsers',
        'property#first_name':new_user_first_name,
        'property#last_name':new_user_last_name,
        'property#email':email_address,
        'property#password':new_user_pwd
        }
  url=settings.PHENOPTIPS_HOST_NAME + '/rest/wikis/xwiki/spaces/XWiki/pages/' + new_user_name + '/objects'
  do_authenticated_POST(admin_uname,admin_pwd,url,data,headers)
  
  

def add_read_only_user_to_phenotips_patient(username,patient_eid):
  '''
    Adds a non-owner phenotips-user to an existing patient. Requires an existing phenotips-user username, patient_eid (PXXXX..).
    Please note: User creation happens ONLY in method "add_new_user_to_phenotips". While this method 
    Is ONLY for associating an existing phenotips-username to a patient and with ONLY read-only capabilities. 
    It DOES NOT create the user account..
  '''
  admin_uname=settings.PHENOTIPS_ADMIN_UNAME
  admin_pwd=settings.PHENOTIPS_ADMIN_PWD
  headers={"Content-Type": "application/x-www-form-urlencoded"}
  data={'collaborator':'XWiki.' + username,
        'patient':patient_eid,
        'accessLevel':'view',
        'xaction':'update',
        'submit':'Update'}
  url = settings.PHENOPTIPS_HOST_NAME + '/bin/get/PhenoTips/PatientAccessRightsManagement?outputSyntax=plain'
  do_authenticated_POST(admin_uname,admin_pwd,url,data,headers)
  
  

def do_authenticated_PUT(uname,pwd,url,data,headers):
  '''
    Do a PUT call to phenotips
  '''
  try:
    request=requests.put(url,data=data,auth=(uname,pwd),headers=headers)
    return request
  except Exception as e:
    print 'error in do_authenticated_PUT:',e,
    raise
  

def do_authenticated_POST(uname,pwd,url,data,headers):
  '''
    Do a POST call to phenotips
  '''
  try:
    request=requests.post(url,data=data,auth=(uname,pwd),headers=headers)
  except Exception as e:
    print 'error in do_authenticated_POST:',e,
    raise