import os
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Google Drive API 접근 권한 (파일 읽기/쓰기/업로드)
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_gdrive_service(user_email="hhokyung@gmail.com", creds_json_path="credentials.json", token_json_path="token.json"):
    """
    Google Drive API 서비스 객체 생성 및 인증 처리
    """
    creds = None
    if os.path.exists(token_json_path):
        try:
            creds = Credentials.from_authorized_user_file(token_json_path, SCOPES)
        except Exception as e:
            print(f"기존 token.json 로드 에러: {e}")

    # 유효한 인증 정보가 없을 경우 인증 수행
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"토큰 갱신 에러: {e}")
                creds = None

        if not creds:
            if not os.path.exists(creds_json_path):
                print("\n" + "!"*80)
                print(f" [Google Drive API 인증 필요 안내] ")
                print(f"계정 ({user_email})으로 구글 드라이브 업로드를 진행하려면 GCP 인증키가 필요합니다.")
                print(f"1. Google Cloud Console에서 OAuth 2.0 데스크톱 클라이언트 JSON 키를 다운로드")
                print(f"2. 해당 파일의 이름을 '{os.path.abspath(creds_json_path)}'로 저장해 주세요.")
                print("!"*80 + "\n")
                return None

            flow = InstalledAppFlow.from_client_secrets_file(creds_json_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # 토큰 저장
        with open(token_json_path, 'w') as token_file:
            token_file.write(creds.to_json())

    service = build('drive', 'v3', credentials=creds)
    return service

def find_or_create_folder(service, folder_name):
    """구글 드라이브 내 특정 폴더 찾기 없으면 자동 생성"""
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = response.get('files', [])

    if files:
        return files[0]['id']
    else:
        # 폴더 생성
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        print(f"구글 드라이브 폴더 생성: '{folder_name}' (ID: {folder['id']})")
        return folder['id']

def upload_pdf_to_gdrive(pdf_file_path, folder_name="CoinSTS_Reports", user_email="hhokyung@gmail.com"):
    """
    지정된 PDF 파일을 구글 드라이브의 해당 폴더로 업로드
    """
    if not os.path.exists(pdf_file_path):
        print(f"업로드 실패: 파일이 존재하지 않습니다 ('{pdf_file_path}')")
        return False

    service = get_gdrive_service(user_email=user_email)
    if not service:
        print(f"Google Drive 서비스 인증이 설정되지 않아 파일 업로드를 스킵합니다.")
        return False

    folder_id = find_or_create_folder(service, folder_name)
    file_name = os.path.basename(pdf_file_path)

    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }

    media = MediaFileUpload(pdf_file_path, mimetype='application/pdf', resumable=True)

    print(f"구글 드라이브 업로드 시작 ({user_email} -> 폴더: '{folder_name}'): {file_name}")
    file = service.files().create(body=file_metadata, media_body=media, fields='id, name, webViewLink').execute()
    
    print(f"★ 구글 드라이브 업로드 완료!\n -> 파일명: {file.get('name')}\n -> 링크: {file.get('webViewLink')}")
    return file.get('webViewLink')

if __name__ == "__main__":
    print("Google Drive 업로드 모듈 테스트")
