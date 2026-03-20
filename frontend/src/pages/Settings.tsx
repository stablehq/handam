import { useEffect, useState } from 'react';
import { Wifi, WifiOff, RefreshCw, Copy, Trash2, BookmarkPlus } from 'lucide-react';
import { toast } from 'sonner';
import { settingsAPI } from '@/services/api';
import { useTenantStore } from '@/stores/tenant-store';
import {
  Button,
  Badge,
  Spinner,
  Textarea,
  Card,
  Alert,
} from 'flowbite-react';

interface NaverStatus {
  has_cookie: boolean;
  cookie_length: number;
  cookie_preview: string;
  is_valid: boolean | null;
  source: string;
  business_id: string;
}

export default function Settings() {
  const [status, setStatus] = useState<NaverStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [cookieInput, setCookieInput] = useState('');
  const [showBookmarklet, setShowBookmarklet] = useState(false);
  const { tenants, currentTenantId } = useTenantStore();

  const fetchStatus = async (showLoading = true) => {
    if (showLoading) setLoading(true);
    else setChecking(true);
    try {
      const res = await settingsAPI.getNaverStatus();
      setStatus(res.data);
    } catch {
      toast.error('상태 확인 실패');
    } finally {
      setLoading(false);
      setChecking(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const handleSaveCookie = async () => {
    if (!cookieInput.trim()) {
      toast.error('쿠키를 입력해주세요');
      return;
    }
    setSaving(true);
    try {
      const res = await settingsAPI.updateNaverCookie(cookieInput.trim());
      toast.success(res.data.message);
      setCookieInput('');
      await fetchStatus(false);
    } catch {
      toast.error('쿠키 저장 실패');
    } finally {
      setSaving(false);
    }
  };

  const handleClearCookie = async () => {
    try {
      await settingsAPI.clearNaverCookie();
      toast.success('.env 쿠키로 복원되었습니다');
      await fetchStatus(false);
    } catch {
      toast.error('초기화 실패');
    }
  };

  const serverUrl = window.location.origin;
  const bookmarkletCode = `javascript:void(fetch('${serverUrl}/api/settings/naver/cookie',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cookie:document.cookie})}).then(r=>r.json()).then(d=>alert(d.message)).catch(e=>alert('Error: '+e)))`;

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Naver Connection Status */}
      <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            네이버 스마트플레이스 연동
          </h2>
          <div className="flex items-center gap-2">
            {status?.is_valid === true && (
              <Badge color="success" icon={() => <Wifi size={12} />}>
                연결됨
              </Badge>
            )}
            {status?.is_valid === false && (
              <Badge color="failure" icon={() => <WifiOff size={12} />}>
                연결 끊김
              </Badge>
            )}
            {status?.is_valid === null && !status?.has_cookie && (
              <Badge color="gray">미설정</Badge>
            )}
            <Button
              size="xs"
              color="light"
              onClick={() => fetchStatus(false)}
              disabled={checking}
            >
              <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
            </Button>
          </div>
        </div>

        <div className="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-400">
          <div className="flex justify-between">
            <span>Business ID</span>
            <span className="font-mono">{status?.business_id}</span>
          </div>
          <div className="flex justify-between">
            <span>쿠키 소스</span>
            <span>{status?.source === 'runtime' ? '직접 입력 (런타임)' : '.env 파일'}</span>
          </div>
          <div className="flex justify-between">
            <span>쿠키 길이</span>
            <span>{status?.cookie_length || 0}자</span>
          </div>
        </div>

        {status?.is_valid === false && (
          <Alert color="failure" className="mt-4">
            쿠키가 만료되었습니다. 새 쿠키를 입력하거나 북마클릿으로 갱신해주세요.
          </Alert>
        )}

        {status?.source === 'runtime' && (
          <div className="mt-3">
            <Button size="xs" color="light" onClick={handleClearCookie}>
              <Trash2 size={14} className="mr-1" />
              런타임 쿠키 초기화 (.env로 복원)
            </Button>
          </div>
        )}
      </Card>

      {/* Cookie Input */}
      <Card>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
          쿠키 직접 입력
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          네이버 스마트플레이스에서 개발자도구(F12) &rarr; Network &rarr; 요청 선택 &rarr; Headers &rarr; Cookie 값을 복사해서 붙여넣으세요.
        </p>

        <Textarea
          className="mt-3 font-mono text-xs"
          rows={4}
          placeholder="NAC=...; NNB=...; NID_AUT=...; NID_SES=...; ..."
          value={cookieInput}
          onChange={(e) => setCookieInput(e.target.value)}
        />

        <div className="mt-3 flex gap-2">
          <Button onClick={handleSaveCookie} disabled={saving || !cookieInput.trim()}>
            {saving ? <Spinner size="sm" className="mr-2" /> : null}
            저장 및 테스트
          </Button>
        </div>
      </Card>

      {/* Bookmarklet */}
      <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            원클릭 쿠키 갱신 (북마클릿)
          </h2>
          <Button
            size="xs"
            color="light"
            onClick={() => setShowBookmarklet(!showBookmarklet)}
          >
            <BookmarkPlus size={14} className="mr-1" />
            {showBookmarklet ? '접기' : '설정 방법 보기'}
          </Button>
        </div>

        {showBookmarklet && (
          <div className="mt-4 space-y-4">
            <Alert color="info">
              <div className="space-y-2">
                <p className="font-semibold">사용법:</p>
                <ol className="list-inside list-decimal space-y-1 text-sm">
                  <li>아래 <strong>"쿠키 전송"</strong> 버튼을 브라우저 <strong>즐겨찾기 바</strong>로 드래그하세요</li>
                  <li>네이버 스마트플레이스 (<code>new.smartplace.naver.com</code>)에 로그인</li>
                  <li>즐겨찾기 바에 추가한 버튼을 클릭</li>
                  <li>자동으로 쿠키가 서버에 전송되고 알림이 표시됩니다</li>
                </ol>
              </div>
            </Alert>

            {/* Draggable bookmarklet button */}
            <div className="flex items-center gap-3">
              <a
                href={bookmarkletCode}
                onClick={(e) => e.preventDefault()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
                title="이 버튼을 즐겨찾기 바로 드래그하세요"
              >
                <Wifi size={14} />
                쿠키 전송
              </a>
              <span className="text-sm text-gray-500">&larr; 즐겨찾기 바로 드래그</span>
            </div>

            {/* Manual copy */}
            <div className="space-y-2">
              <p className="text-sm text-gray-500 dark:text-gray-400">
                드래그가 안 되면 아래 코드를 복사해서 즐겨찾기 URL에 붙여넣으세요:
              </p>
              <div className="relative">
                <pre className="overflow-x-auto rounded-lg bg-gray-100 p-3 text-xs dark:bg-gray-800">
                  {bookmarkletCode}
                </pre>
                <Button
                  size="xs"
                  color="light"
                  className="absolute right-2 top-2"
                  onClick={() => {
                    navigator.clipboard.writeText(bookmarkletCode);
                    toast.success('복사되었습니다');
                  }}
                >
                  <Copy size={12} />
                </Button>
              </div>
            </div>
          </div>
        )}
      </Card>

      {/* Tenant switch */}
      {tenants.length > 1 && (
        <div className="flex items-center gap-3">
          {tenants.map((t) => (
            <Button
              key={t.id}
              color={String(t.id) === currentTenantId ? 'blue' : 'light'}
              size="sm"
              onClick={() => {
                localStorage.setItem('sms-tenant-id', String(t.id))
                window.location.reload()
              }}
            >
              {t.slug === 'stable' ? 'CANCEL' : t.name}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
