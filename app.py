import io, re, datetime
import streamlit as st
from PIL import Image, ImageOps
from google.oauth2 import service_account
from google.cloud import vision
import gspread
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

st.set_page_config(page_title='VFS Asset Scanner', page_icon='📷', layout='centered')
st.title('📷 VFS Asset Scanner')
st.caption('Photograph → Read → Verify → Save')

SCOPES=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive.file','https://www.googleapis.com/auth/cloud-vision']

def creds():
    return service_account.Credentials.from_service_account_info(dict(st.secrets['google_service_account']),scopes=SCOPES)

def ocr(photo):
    client=vision.ImageAnnotatorClient(credentials=creds())
    result=client.document_text_detection(image=vision.Image(content=photo))
    if result.error.message: raise RuntimeError(result.error.message)
    return result.full_text_annotation.text or ''

def vt_guess(text):
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    for i,line in enumerate(lines):
        if re.search(r'MACHINE\s*#|MACHINE\s*(?:NO|NUMBER)|ASSET\s*(?:#|NO|NUMBER)|\bVT\s*#',line,re.I):
            m=re.search(r'(?<!\d)\d{4,9}(?!\d)',line)
            if m:return m.group()
            if i+1<len(lines):
                m=re.search(r'(?<!\d)\d{4,9}(?!\d)',lines[i+1])
                if m:return m.group()
    candidates=re.findall(r'(?<!\d)\d{5,7}(?!\d)',text)
    return candidates[0] if len(candidates)==1 else ''

def reader_guess(text):
    m=re.search(r'\bIMEI\s*[:#-]?\s*(\d[\d\s-]{12,20}\d)',text,re.I)
    if m:
        v=re.sub(r'\D','',m.group(1))
        if len(v)==15:return v
    m=re.search(r'(?<!\d)\d{15}(?!\d)',text)
    if m:return m.group()
    for line in text.splitlines():
        for match in re.findall(r'\b[A-Z]{1,4}\d{7,15}\b',line.upper()):
            return match
    return ''

def upload_photo(drive, folder_id, name, content):
    metadata={'name':name,'parents':[folder_id]}
    media=MediaIoBaseUpload(io.BytesIO(content),mimetype='image/jpeg',resumable=False)
    obj=drive.files().create(body=metadata,media_body=media,fields='id,webViewLink',supportsAllDrives=True).execute()
    return obj.get('webViewLink') or 'https://drive.google.com/file/d/'+obj['id']+'/view'

def save_record(employee, vt, reader, kind, vt_bytes, reader_bytes):
    c=creds()
    sheet_id=st.secrets['app']['spreadsheet_id']
    folder_id=st.secrets['app']['drive_folder_id']
    gc=gspread.authorize(c)
    ws=gc.open_by_key(sheet_id).sheet1
    headers=['Timestamp (UTC)','Employee','VT Asset Number','Reader Identifier','Reader ID Type','VT Photo','Reader Photo']
    if not ws.row_values(1):ws.append_row(headers)
    existing=ws.col_values(3)[1:]
    if vt in existing:raise ValueError('This VT number already exists in the sheet. Please review the existing record before saving.')
    drive=build('drive','v3',credentials=c,cache_discovery=False)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
    vt_link=upload_photo(drive,folder_id,f'{vt}_{stamp}_VT.jpg',vt_bytes)
    reader_link=upload_photo(drive,folder_id,f'{vt}_{stamp}_READER.jpg',reader_bytes)
    ws.append_row([datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),employee,vt,reader,kind,vt_link,reader_link],value_input_option='RAW')

if 'last_vt' not in st.session_state:st.session_state.last_vt=''
if 'last_reader' not in st.session_state:st.session_state.last_reader=''

employee=st.text_input('Employee name',placeholder='First and last name')

st.subheader('1. VT machine tag')
vt_source=st.radio('VT photo source',['Take photo','Upload photo'],horizontal=True,key='vtsrc')
vt_file=st.camera_input('Photograph VT tag',key='vtcam') if vt_source=='Take photo' else st.file_uploader('Upload VT tag photo',type=['jpg','jpeg','png'],key='vtup')
vt_bytes=None
if vt_file:
    vt_bytes=vt_file.getvalue()
    st.image(vt_bytes,caption='VT label',width=280)
    if st.button('Read VT number from photo',use_container_width=True):
        try:
            with st.spinner('Reading handwritten tag…'):
                raw=ocr(vt_bytes)
                st.session_state['vt_value']=vt_guess(raw)
                st.session_state['vt_ocr_raw']=raw
                st.session_state['vt_verified']=False
            if not st.session_state['vt_value']:st.warning('No confident VT match. Review the photo and enter the number manually.')
        except Exception as e:st.error(f'OCR failed: {e}')
vt=st.text_input('Extracted VT number — correct if needed',key='vt_value')
vt_verified=st.checkbox('I checked this VT number against the machine tag',key='vt_verified')

st.subheader('2. Credit card reader label')
st.caption('Capture the IMEI label when available. Some ePort units show a reader serial number instead.')
reader_source=st.radio('Reader photo source',['Take photo','Upload photo'],horizontal=True,key='rdsrc')
reader_file=st.camera_input('Photograph reader label',key='rdcam') if reader_source=='Take photo' else st.file_uploader('Upload reader label photo',type=['jpg','jpeg','png'],key='rdup')
reader_bytes=None
if reader_file:
    reader_bytes=reader_file.getvalue()
    st.image(reader_bytes,caption='Reader label',width=280)
    if st.button('Read reader number from photo',use_container_width=True):
        try:
            with st.spinner('Reading reader label…'):
                raw=ocr(reader_bytes)
                st.session_state['reader_value']=reader_guess(raw)
                st.session_state['reader_ocr_raw']=raw
                st.session_state['reader_verified']=False
            if not st.session_state['reader_value']:st.warning('No confident reader number found. Enter the number manually.')
        except Exception as e:st.error(f'OCR failed: {e}')
reader=st.text_input('Extracted reader number — correct if needed',key='reader_value')
kind=st.selectbox('Reader identifier type',['IMEI (15 digits)','Serial number / other ID'])
reader_verified=st.checkbox('I checked this number against the reader label',key='reader_verified')

valid=bool(employee.strip() and vt_bytes and reader_bytes and vt.strip() and reader.strip() and vt_verified and reader_verified)
if kind=='IMEI (15 digits)' and reader and not re.fullmatch(r'\d{15}',reader.strip()):
    st.warning('An IMEI must be exactly 15 digits. If this is a printed serial number, choose “Serial number / other ID”.')
    valid=False
if st.button('✅ Submit verified asset',type='primary',use_container_width=True,disabled=not valid):
    try:
        with st.spinner('Saving photos and spreadsheet record…'):
            save_record(employee.strip(),vt.strip(),reader.strip(),kind,vt_bytes,reader_bytes)
        st.success('Asset saved to Google Sheets and photos saved to Google Drive.')
        st.balloons()
    except KeyError:
        st.error('Google credentials or sheet/folder IDs are not configured. See README.md.')
    except Exception as e:st.error(f'Save failed: {e}')

with st.expander('OCR troubleshooting'):
    st.caption('If the extracted number is incorrect, correct it before verifying. Recognition is not guaranteed, particularly for handwriting.')
    if st.session_state.get('vt_ocr_raw'):st.code(st.session_state['vt_ocr_raw'])
    if st.session_state.get('reader_ocr_raw'):st.code(st.session_state['reader_ocr_raw'])
