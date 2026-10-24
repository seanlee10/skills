# 연결과 로컬 설정

## 시트 대상

현재 요청에서 시트를 지정하면 그 대상을 사용한다. 지정이 없으면 `~/.config/naver-research/profile.json`을 읽는다.
아래 형식의 로컬 파일에 대상과 작업 기준만 보관한다. 자격 증명은 저장하지 않는다.

```json
{
  "spreadsheet_id": "YOUR_SPREADSHEET_ID",
  "sheet_name": "plan",
  "blog_url": "https://example.com/blog",
  "timezone": "Asia/Seoul",
  "measurement_lead_days": 14
}
```

기본 측정·작성 소요는 14일이다. 요청이 있으면 7~14일 범위에서 실제 소요로 조정한다.
Google Sheets 도구로 메타데이터를 먼저 확인하고, 확인한 탭의 헤더와 후보 범위만 읽는다.
기본 헤더는 `id`, `제목`, `유형`, `목표 발행일`, `브리프`, `상태`, `포스트 링크`다.
한글 헤더를 실제 열에 매핑한다. 개인 시트 ID와 블로그 주소를 스킬 본문·예제·공개 테스트에 넣지 않는다.
로컬 프로필은 접근 대상을 지정할 뿐 쓰기를 승인하지 않는다.

## 네이버 MCP

[isnow890/naver-search-mcp](https://github.com/isnow890/naver-search-mcp)는 MIT 라이선스의 외부 프로젝트다.
이 스킬은 해당 프로젝트를 복제하거나 번들하지 않고, 연결된 도구를 사용한다.
호스트의 MCP 설정에서 실행할 패키지는 `@isnow890/naver-search-mcp`다.
확인한 upstream 버전은 `1.0.54`이며 Node.js와 npx가 필요하다.
새 서버를 연결할 때 기존 MCP 설정을 덮어쓰지 말고 호스트의 설치 절차를 따른다.
스킬 설치만으로 MCP 서버 연결이나 네이버 인증이 완료되는 것은 아니다.

2026-10-24에 확인한 인증 방식은 다음과 같다.

| 발급 경로 | MCP 서버 프로세스에 제공할 환경변수 | 적용 범위 |
| --- | --- | --- |
| NAVER API HUB | `NCP_APIGW_API_KEY_ID`, `NCP_APIGW_API_KEY` | 신규 발급과 권장 경로 |
| 네이버 개발자센터 | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 기존 신청자 전용 유예 경로 |

현재 upstream은 어느 환경변수 쌍을 제공했는지로 플랫폼을 선택한다. 한 쌍만 설정하고 플랫폼별 키를 섞지 않는다.
필요한 API는 검색어 트렌드와 쇼핑 인사이트다. 키는 사용자가 로컬 환경에 설정하며 채팅·로그·공개 파일에는 넣지 않는다.
스킬 실행 프로세스의 환경변수가 비어 있다는 사실만으로 별도 MCP 서버에도 키가 없다고 단정하지 않는다.
실제 연결 도구와 인증된 호출 결과로 확인한다.

공식 이관 일정에 따라 개발자센터 신규 신청은 2026-07-31에 차단됐으며 기존 키 지원은 2027-06-30에 종료된다.
신규 사용자를 개발자센터의 옛 신청 안내로 보내지 말고 NAVER API HUB에서 키를 발급받도록 안내한다.
이후 실행에서는 [공식 이관 공지](https://developers.naver.com/notice/article/32530)와 현재 upstream 안내를 다시 확인한다.

## 도구 이름과 한도

현재 upstream에서 확인한 이름은 `datalab_search`, `find_category`, `datalab_shopping_category`,
`datalab_shopping_keywords`다. 호스트는 이름 앞에 서버 접두사를 붙일 수 있다.
실행 직전에 도구 목록과 입력 스키마를 확인한다. 쇼핑 검색 API와 쇼핑인사이트는 서로 다른 API다.

검색어트렌드는 요청당 최대 5묶음, 묶음당 최대 20검색어다. 기준 묶음을 포함하면 후보는 배치당 최대 4개다.
쇼핑 분야별 트렌드는 요청당 최대 3분야다. 검색어 API의 연령 코드와 쇼핑 API의 연령 코드는 서로 다르다.
필터를 쓰려면 각각의 스키마에 맞게 설정하고, 기본적으로 전체 기기·성별·연령을 유지한다.

기존 개발자센터 검색어트렌드 문서는 하루 1,000회 한도를 명시한다.
API HUB의 현재 계정·상품 한도는 콘솔에서 별도로 확인하며, 옛 무료 한도를 새 상품의 보장값으로 쓰지 않는다.
29후보의 최초 검색 비교는 `ceil(29/4)=8`회다. 쇼핑·카테고리·추가 과거 기간·재시도 호출은 별도다.
401·403은 인증·권한 확인 후 멈추고, 일일 한도 429에서는 반복하지 않는다.
일시적인 서버·네트워크 오류는 짧게 기다린 뒤 1회만 재시도한다. 빈 데이터나 오류 본문을 관심도 0으로 읽지 않는다.

## 공식 자료

- [API HUB 인증과 오류 응답](https://api.ncloud-docs.com/docs/naver-api-hub-overview).
- [API HUB 검색어 트렌드](https://api.ncloud-docs.com/docs/naver-api-hub-search-trend).
- [API HUB 쇼핑 분야별 클릭 트렌드](https://api.ncloud-docs.com/docs/naver-api-hub-shopping-insight-categories).
- [기존 검색어트렌드 한도와 응답 명세](https://developers.naver.com/docs/serviceapi/datalab/search/search.md).
