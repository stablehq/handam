import { useEffect, useState } from 'react';
import { Wifi, WifiOff, RefreshCw, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { settingsAPI } from '@/services/api';
import { useTenantStore } from '@/stores/tenant-store';
import { Card } from '@/components/ui/card';
import { Alert } from '@/components/ui/alert';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Spinner } from '@/components/ui/spinner';
import { Button } from '@/components/ui/button';

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
  const { tenants, currentTenantId } = useTenantStore();
  const currentTenant = tenants.find(t => String(t.id) === currentTenantId);
  const hasUnstable = currentTenant?.has_unstable ?? false;
  const tenantLabel = currentTenant?.name || currentTenant?.slug || '네이버';

  // Unstable state
  const [unstableStatus, setUnstableStatus] = useState<NaverStatus | null>(null);
  const [unstableChecking, setUnstableChecking] = useState(false);
  const [unstableSaving, setUnstableSaving] = useState(false);
  const [unstableSyncing, setUnstableSyncing] = useState(false);
  const [unstableBusinessId, setUnstableBusinessId] = useState('');
  const [unstableCookieInput, setUnstableCookieInput] = useState('');


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

  const fetchUnstableStatus = async (showLoading = false) => {
    if (showLoading) setLoading(true);
    else setUnstableChecking(true);
    try {
      const res = await settingsAPI.getUnstableStatus();
      setUnstableStatus(res.data);
      if (res.data.business_id && !unstableBusinessId) {
        setUnstableBusinessId(res.data.business_id);
      }
    } catch {
      // unstable 미설정 시 무시
    } finally {
      setLoading(false);
      setUnstableChecking(false);
    }
  };


  useEffect(() => {
    fetchStatus();
    fetchUnstableStatus(true);

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

  const handleSaveUnstable = async () => {
    if (!unstableBusinessId.trim() && !unstableCookieInput.trim()) {
      toast.error('Business ID 또는 쿠키를 입력해주세요');
      return;
    }
    setUnstableSaving(true);
    try {
      const data: { business_id?: string; cookie?: string } = {};
      if (unstableBusinessId.trim()) data.business_id = unstableBusinessId.trim();
      if (unstableCookieInput.trim()) data.cookie = unstableCookieInput.trim();
      const res = await settingsAPI.updateUnstableSettings(data);
      toast.success(res.data.message);
      if (res.data.warning) toast.warning(res.data.warning);
      setUnstableCookieInput('');
      await fetchUnstableStatus();
    } catch {
      toast.error('언스테이블 설정 저장 실패');
    } finally {
      setUnstableSaving(false);
    }
  };

  const handleSyncUnstable = async () => {
    setUnstableSyncing(true);
    try {
      const res = await settingsAPI.syncUnstable();
      if (res.data.success) {
        toast.success(res.data.message);
      } else {
        toast.error(res.data.message);
      }
    } catch {
      toast.error('언스테이블 동기화 실패');
    } finally {
      setUnstableSyncing(false);
    }
  };



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
            {tenantLabel} 네이버 연동
          </h2>
          <div className="flex items-center gap-2">
            {status?.is_valid === true && (
              <Badge color="success" icon={Wifi}>
                연결됨
              </Badge>
            )}
            {status?.is_valid === false && (
              <Badge color="failure" icon={WifiOff}>
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
            쿠키가 만료되었습니다. 새 쿠키를 입력해주세요.
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


      {/* Unstable Naver Connection Status */}
      {hasUnstable && <Card>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            언스테이블 네이버 연동
          </h2>
          <div className="flex items-center gap-2">
            {unstableStatus?.is_valid === true && (
              <Badge color="success" icon={Wifi}>연결됨</Badge>
            )}
            {unstableStatus?.is_valid === false && (
              <Badge color="failure" icon={WifiOff}>연결 끊김</Badge>
            )}
            {(!unstableStatus || (unstableStatus?.is_valid === null && !unstableStatus?.has_cookie)) && (
              <Badge color="gray">미설정</Badge>
            )}
            <Button
              size="xs"
              color="light"
              onClick={() => fetchUnstableStatus()}
              disabled={unstableChecking}
            >
              <RefreshCw size={14} className={unstableChecking ? 'animate-spin' : ''} />
            </Button>
          </div>
        </div>

        {unstableStatus?.has_cookie && (
          <div className="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-400">
            <div className="flex justify-between">
              <span>Business ID</span>
              <span className="font-mono">{unstableStatus.business_id}</span>
            </div>
            <div className="flex justify-between">
              <span>쿠키 길이</span>
              <span>{unstableStatus.cookie_length || 0}자</span>
            </div>
          </div>
        )}

        {unstableStatus?.is_valid === false && (
          <Alert color="failure" className="mt-4">
            쿠키가 만료되었습니다. 새 쿠키를 입력해주세요.
          </Alert>
        )}
      </Card>}

      {/* Unstable Settings Input */}
      {hasUnstable && <Card>
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
          언스테이블 설정
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          언스테이블 네이버 스마트플레이스의 Business ID와 쿠키를 입력하세요.
        </p>

        <div className="mt-3 space-y-3">
          <div>
            <label className="text-caption font-medium text-gray-700 dark:text-gray-300">Business ID</label>
            <input
              type="text"
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono dark:border-gray-600 dark:bg-gray-800 dark:text-white"
              placeholder="1000256"
              value={unstableBusinessId}
              onChange={(e) => setUnstableBusinessId(e.target.value)}
            />
          </div>
          <div>
            <label className="text-caption font-medium text-gray-700 dark:text-gray-300">쿠키</label>
            <Textarea
              className="mt-1 font-mono text-xs"
              rows={4}
              placeholder="NAC=...; NNB=...; NID_AUT=...; NID_SES=...; ..."
              value={unstableCookieInput}
              onChange={(e) => setUnstableCookieInput(e.target.value)}
            />
          </div>
        </div>

        <div className="mt-3 flex gap-2">
          <Button onClick={handleSaveUnstable} disabled={unstableSaving || (!unstableBusinessId.trim() && !unstableCookieInput.trim())}>
            {unstableSaving ? <Spinner size="sm" className="mr-2" /> : null}
            저장 및 테스트
          </Button>
          {unstableStatus?.is_valid && (
            <Button color="light" onClick={handleSyncUnstable} disabled={unstableSyncing}>
              {unstableSyncing ? <Spinner size="sm" className="mr-2" /> : <RefreshCw size={14} className="mr-1.5" />}
              수동 동기화
            </Button>
          )}
        </div>
      </Card>}


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
