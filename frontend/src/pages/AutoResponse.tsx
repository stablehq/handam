import { useEffect, useRef, useState } from 'react';
import { Zap, Plus, Pencil, Trash2, FileText, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { rulesAPI, documentsAPI } from '@/services/api';

import { Card } from '@/components/ui/card';
import { ToggleSwitch } from '@/components/ui/toggle-switch';
import { Tabs, TabItem } from '@/components/ui/tabs';
import { Table, TableHead, TableBody, TableRow, TableHeadCell, TableCell } from '@/components/ui/table';
import { Modal, ModalHeader, ModalBody, ModalFooter } from '@/components/ui/modal';
import { TextInput } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';
import { Button } from '@/components/ui/button';

interface Rule {
  id: number;
  name: string;
  pattern: string;
  response: string;
  priority: number;
  active: boolean;
}

interface Doc {
  id: number;
  filename: string;
  uploaded_at: string;
  indexed: boolean;
}

interface RuleForm {
  name: string;
  pattern: string;
  response: string;
  priority: number;
  active: boolean;
}

const EMPTY_RULE: RuleForm = {
  name: '',
  pattern: '',
  response: '',
  priority: 0,
  active: true,
};

const AutoResponse = () => {
  const [rules, setRules] = useState<Rule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<RuleForm>(EMPTY_RULE);
  const [saving, setSaving] = useState(false);

  const [documents, setDocuments] = useState<Doc[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadRules();
    loadDocuments();
  }, []);

  const loadRules = async () => {
    setRulesLoading(true);
    try {
      const res = await rulesAPI.getAll();
      setRules(res.data);
    } catch {
      toast.error('규칙 목록 로드 실패');
    } finally {
      setRulesLoading(false);
    }
  };

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_RULE);
    setDialogOpen(true);
  };

  const openEdit = (rule: Rule) => {
    setEditingId(rule.id);
    setForm({
      name: rule.name,
      pattern: rule.pattern,
      response: rule.response,
      priority: rule.priority,
      active: rule.active,
    });
    setDialogOpen(true);
  };

  const handleDeleteRule = async (id: number) => {
    try {
      await rulesAPI.delete(id);
      toast.success('룰 삭제 완료');
      loadRules();
    } catch {
      toast.error('룰 삭제 실패');
    }
  };

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.pattern.trim() || !form.response.trim()) {
      toast.error('이름, 패턴, 응답은 필수입니다');
      return;
    }
    setSaving(true);
    try {
      if (editingId !== null) {
        await rulesAPI.update(editingId, form);
        toast.success('룰 수정 완료');
      } else {
        await rulesAPI.create(form);
        toast.success('룰 생성 완료');
      }
      setDialogOpen(false);
      loadRules();
    } catch {
      toast.error('룰 저장 실패');
    } finally {
      setSaving(false);
    }
  };

  const loadDocuments = async () => {
    setDocsLoading(true);
    try {
      const res = await documentsAPI.getAll();
      setDocuments(res.data);
    } catch {
      toast.error('문서 목록 로드 실패');
    } finally {
      setDocsLoading(false);
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await documentsAPI.upload(file);
      toast.success(`${file.name} 업로드 완료 (Demo 모드)`);
      loadDocuments();
    } catch {
      toast.error('업로드 실패');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDeleteDoc = async (id: number) => {
    try {
      await documentsAPI.delete(id);
      toast.success('문서 삭제 완료');
      loadDocuments();
    } catch {
      toast.error('문서 삭제 실패');
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2.5">
          <div className="stat-icon bg-[#F3EEFF] text-[#7B61FF] dark:bg-[#7B61FF]/15 dark:text-[#7B61FF]">
            <Zap size={20} />
          </div>
          <div>
            <h1 className="page-title">자동 응답 관리</h1>
            <p className="page-subtitle">규칙 기반 자동 응답과 지식 문서를 관리합니다.</p>
          </div>
        </div>
      </div>

      <Tabs variant="underline">
        <TabItem active title="응답 규칙">
          <div className="section-card">
            <div className="section-header">
              <h3 className="text-body font-semibold text-[#191F28] dark:text-white">응답 규칙 목록</h3>
              <Button color="blue" size="sm" onClick={openCreate}>
                <Plus className="mr-1.5 h-4 w-4" />
                룰 추가
              </Button>
            </div>

            {rulesLoading ? (
              <div className="flex items-center justify-center py-16">
                <Spinner size="lg" />
              </div>
            ) : rules.length === 0 ? (
              <div className="empty-state">
                <Zap size={40} strokeWidth={1} />
                <p className="text-body">등록된 규칙이 없습니다</p>
              </div>
            ) : (
                <Table hoverable striped>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell>ID</TableHeadCell>
                      <TableHeadCell>이름</TableHeadCell>
                      <TableHeadCell>패턴 (정규식)</TableHeadCell>
                      <TableHeadCell>응답</TableHeadCell>
                      <TableHeadCell>우선순위</TableHeadCell>
                      <TableHeadCell>활성화</TableHeadCell>
                      <TableHeadCell>작업</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody className="divide-y">
                    {rules.map((rule) => (
                      <TableRow key={rule.id}>
                        <TableCell>
                          <span className="tabular-nums text-gray-400">#{rule.id}</span>
                        </TableCell>
                        <TableCell>
                          <span className="font-medium text-gray-900 dark:text-white">{rule.name}</span>
                        </TableCell>
                        <TableCell>
                          <code className="rounded-lg bg-gray-100 px-1.5 py-0.5 font-mono text-caption text-blue-600 dark:bg-gray-700">
                            {rule.pattern}
                          </code>
                        </TableCell>
                        <TableCell>
                          <span className="line-clamp-2 max-w-[240px] text-body text-gray-600 dark:text-gray-300">
                            {rule.response}
                          </span>
                        </TableCell>
                        <TableCell>
                          <Badge color="gray">{rule.priority}</Badge>
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-center">
                            <ToggleSwitch checked={rule.active} onChange={() => {}} label="" disabled />
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <Button color="light" size="xs" onClick={() => openEdit(rule)}>
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button color="light" size="xs" onClick={() => handleDeleteRule(rule.id)}>
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
            )}
          </div>
        </TabItem>

        <TabItem title="지식 문서">
          <div className="section-card">
            <div className="section-header">
              <h3 className="text-body font-semibold text-[#191F28] dark:text-white">지식 문서</h3>
              <div>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={handleFileChange}
                />
                <Button
                  color="blue"
                  size="sm"
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading ? (
                    <>
                      <Spinner size="sm" className="mr-1.5" />
                      업로드 중...
                    </>
                  ) : (
                    <>
                      <Upload className="mr-1.5 h-4 w-4" />
                      문서 업로드
                    </>
                  )}
                </Button>
              </div>
            </div>

            {/* Info notice — Toss style */}
            <div className="mx-5 mt-4 rounded-xl bg-[#E8F3FF] px-4 py-3 text-label text-[#3182F6] dark:bg-[#3182F6]/10">
              Demo 모드: 문서는 메타데이터만 저장되며 실제로 RAG 인덱싱되지 않습니다.
              프로덕션 모드에서는 ChromaDB에 임베딩되어 LLM 응답 생성 시 활용됩니다.
            </div>

            {docsLoading ? (
              <div className="flex items-center justify-center py-16">
                <Spinner size="lg" />
              </div>
            ) : documents.length === 0 ? (
              <div className="empty-state">
                <FileText size={40} strokeWidth={1} />
                <p className="text-body">업로드된 문서가 없습니다</p>
              </div>
            ) : (
              <div className="p-5 pt-4">
                <Table hoverable striped>
                  <TableHead>
                    <TableRow>
                      <TableHeadCell>ID</TableHeadCell>
                      <TableHeadCell>파일명</TableHeadCell>
                      <TableHeadCell>업로드 시간</TableHeadCell>
                      <TableHeadCell>인덱싱 상태</TableHeadCell>
                      <TableHeadCell>삭제</TableHeadCell>
                    </TableRow>
                  </TableHead>
                  <TableBody className="divide-y">
                    {documents.map((doc) => (
                      <TableRow key={doc.id}>
                        <TableCell>
                          <span className="tabular-nums text-gray-400">#{doc.id}</span>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <FileText className="h-4 w-4 shrink-0 text-gray-400" />
                            <span className="font-medium text-gray-900 dark:text-white">{doc.filename}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <span className="text-body text-gray-500">
                            {new Date(doc.uploaded_at).toLocaleString('ko-KR')}
                          </span>
                        </TableCell>
                        <TableCell>
                          {doc.indexed ? (
                            <Badge color="success">완료</Badge>
                          ) : (
                            <Badge color="gray">대기중</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <Button color="light" size="xs" onClick={() => handleDeleteDoc(doc.id)}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        </TabItem>
      </Tabs>

      {/* Rule Modal */}
      <Modal show={dialogOpen} onClose={() => setDialogOpen(false)} size="lg">
        <ModalHeader>{editingId !== null ? '룰 수정' : '룰 추가'}</ModalHeader>
        <ModalBody>
          <div className="flex flex-col gap-5">
            <div className="space-y-2">
              <Label htmlFor="rule-name">이름 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
              <TextInput
                id="rule-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="영업시간 안내"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-pattern">패턴 (정규식) <span className="text-[#F04452] dark:text-red-400">*</span></Label>
              <TextInput
                id="rule-pattern"
                value={form.pattern}
                onChange={(e) => setForm((f) => ({ ...f, pattern: e.target.value }))}
                placeholder="(영업시간|몇시|언제)"
              />
              <p className="text-caption text-[#B0B8C1] dark:text-gray-600">정규식 패턴으로 수신 메시지를 매칭합니다</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-response">응답 <span className="text-[#F04452] dark:text-red-400">*</span></Label>
              <Textarea
                id="rule-response"
                rows={4}
                value={form.response}
                onChange={(e) => setForm((f) => ({ ...f, response: e.target.value }))}
                placeholder="안녕하세요! 저희 영업시간은 ..."
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="rule-priority">우선순위</Label>
              <TextInput
                id="rule-priority"
                type="number"
                min={0}
                max={100}
                value={form.priority}
                onChange={(e) => setForm((f) => ({ ...f, priority: Number(e.target.value) }))}
              />
              <p className="text-caption text-[#B0B8C1] dark:text-gray-600">높은 숫자가 우선 매칭됩니다</p>
            </div>

            <ToggleSwitch
              checked={form.active}
              onChange={(v) => setForm((f) => ({ ...f, active: v }))}
              label="활성화"
            />
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="light" onClick={() => setDialogOpen(false)}>취소</Button>
          <Button color="blue" onClick={handleSubmit} disabled={saving}>
            {saving ? (
              <>
                <Spinner size="sm" className="mr-2" />
                저장 중...
              </>
            ) : (
              '저장'
            )}
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default AutoResponse;
