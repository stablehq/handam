import { useState, useEffect } from 'react'
import {
  Button,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Label,
  TextInput,
  Select,
  Spinner,
  Table,
  TableHead,
  TableHeadCell,
  TableBody,
  TableRow,
  TableCell,
} from 'flowbite-react'
import { UserPlus, TriangleAlert, Pencil } from 'lucide-react'
import { authAPI } from '@/services/api'
import { useAuthStore } from '@/stores/auth-store'

interface User {
  id: number
  username: string
  name: string
  role: 'superadmin' | 'admin' | 'staff'
  active: boolean
  created_at?: string
}

const ROLE_LABELS: Record<string, string> = {
  superadmin: '슈퍼관리자',
  admin: '관리자',
  staff: '직원',
}

const ROLE_COLORS: Record<string, string> = {
  superadmin: '#8B5CF6',
  admin: '#3182F6',
  staff: '#8B95A1',
}

const STATUS_COLORS: Record<string, string> = {
  active: '#00C9A7',
  inactive: '#F04452',
}

function formatDate(dateStr?: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString('ko-KR')
}

export default function UserManagement() {
  const currentUser = useAuthStore((s) => s.user)
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)

  // Create modal
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState({ username: '', password: '', name: '', role: 'staff' })
  const [createLoading, setCreateLoading] = useState(false)
  const [createError, setCreateError] = useState('')

  // Edit modal
  const [editOpen, setEditOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<User | null>(null)
  const [editForm, setEditForm] = useState({ username: '', name: '', role: 'staff', password: '' })
  const [editLoading, setEditLoading] = useState(false)
  const [editError, setEditError] = useState('')

  // Delete modal
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)

  const fetchUsers = async () => {
    try {
      setLoading(true)
      const res = await authAPI.getUsers()
      setUsers(res.data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchUsers()
  }, [])

  // Role options filtered by current user's role
  const roleOptions = currentUser?.role === 'superadmin'
    ? [{ value: 'admin', label: '관리자' }, { value: 'staff', label: '직원' }]
    : [{ value: 'staff', label: '직원' }]

  // Create
  const openCreate = () => {
    setCreateForm({ username: '', password: '', name: '', role: roleOptions[0]?.value || 'staff' })
    setCreateError('')
    setCreateOpen(true)
  }

  const handleCreate = async () => {
    if (!createForm.username || !createForm.password || !createForm.name) {
      setCreateError('모든 필드를 입력하세요.')
      return
    }
    setCreateLoading(true)
    setCreateError('')
    try {
      await authAPI.createUser(createForm)
      setCreateOpen(false)
      fetchUsers()
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      setCreateError(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : '생성에 실패했습니다.')
    } finally {
      setCreateLoading(false)
    }
  }

  // Edit
  const openEdit = (user: User) => {
    setEditTarget(user)
    setEditForm({ username: user.username, name: user.name, role: user.role, password: '' })
    setEditError('')
    setEditOpen(true)
  }

  const handleEdit = async () => {
    if (!editTarget) return
    setEditLoading(true)
    setEditError('')
    try {
      const data: any = { username: editForm.username, name: editForm.name, role: editForm.role }
      if (editForm.password) data.password = editForm.password
      await authAPI.updateUser(editTarget.id, data)
      setEditOpen(false)
      fetchUsers()
    } catch (err: any) {
      const editDetail = err?.response?.data?.detail
      setEditError(typeof editDetail === 'string' ? editDetail : Array.isArray(editDetail) ? editDetail.map((d: any) => d.msg).join(', ') : '수정에 실패했습니다.')
    } finally {
      setEditLoading(false)
    }
  }

  // Delete (deactivate)
  const openDelete = (user: User) => {
    setDeleteTarget(user)
    setDeleteOpen(true)
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleteLoading(true)
    try {
      await authAPI.deleteUser(deleteTarget.id)
      setDeleteOpen(false)
      fetchUsers()
    } catch {
      // silent
    } finally {
      setDeleteLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title">계정 관리</h1>
          <p className="page-subtitle">사용자 계정을 관리합니다</p>
        </div>
        <Button color="blue" size="sm" onClick={openCreate}>
          <UserPlus className="mr-1.5 h-3.5 w-3.5" />
          계정 추가
        </Button>
      </div>

      {/* Table */}
      <div className="section-card overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size="lg" />
          </div>
        ) : users.length === 0 ? (
          <div className="empty-state">
            <p className="text-label text-[#8B95A1]">등록된 사용자가 없습니다.</p>
          </div>
        ) : (
          <Table hoverable>
            <TableHead>
              <TableRow>
                <TableHeadCell className="text-caption">아이디</TableHeadCell>
                <TableHeadCell className="text-caption">이름</TableHeadCell>
                <TableHeadCell className="text-caption">역할</TableHeadCell>
                <TableHeadCell className="text-caption">상태</TableHeadCell>
                <TableHeadCell className="text-caption">생성일</TableHeadCell>
                <TableHeadCell className="text-caption">관리</TableHeadCell>
              </TableRow>
            </TableHead>
            <TableBody className="divide-y">
              {users.map((user) => (
                <TableRow key={user.id} className="bg-white [&>td]:align-middle dark:border-gray-700 dark:bg-gray-800">
                  <TableCell className="text-body font-medium text-[#191F28] dark:text-white">
                    {user.username}
                  </TableCell>
                  <TableCell className="text-body text-[#4E5968] dark:text-gray-300">
                    {user.name}
                  </TableCell>
                  <TableCell>
                    <span className="text-label font-medium" style={{ color: ROLE_COLORS[user.role] }}>
                      {ROLE_LABELS[user.role] || user.role}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-label font-medium" style={{ color: user.active ? STATUS_COLORS.active : STATUS_COLORS.inactive }}>
                      {user.active ? '활성' : '비활성'}
                    </span>
                  </TableCell>
                  <TableCell className="text-caption text-[#8B95A1]">
                    {formatDate(user.created_at)}
                  </TableCell>
                  <TableCell>
                    <button
                      onClick={() => openEdit(user)}
                      className="flex items-center gap-1 text-label font-medium text-[#8B95A1] hover:text-[#4E5968]"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      edit
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Create Modal */}
      <Modal show={createOpen} size="md" onClose={() => setCreateOpen(false)}>
        <ModalHeader>계정 추가</ModalHeader>
        <ModalBody>
          <div className="flex flex-col gap-4">
            <div>
              <Label htmlFor="c-username" className="mb-1.5 block text-label font-medium">아이디</Label>
              <TextInput
                id="c-username"
                placeholder="아이디"
                value={createForm.username}
                onChange={(e) => setCreateForm((f) => ({ ...f, username: e.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="c-password" className="mb-1.5 block text-label font-medium">비밀번호</Label>
              <TextInput
                id="c-password"
                type="password"
                placeholder="비밀번호"
                value={createForm.password}
                onChange={(e) => setCreateForm((f) => ({ ...f, password: e.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="c-name" className="mb-1.5 block text-label font-medium">이름</Label>
              <TextInput
                id="c-name"
                placeholder="이름"
                value={createForm.name}
                onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="c-role" className="mb-1.5 block text-label font-medium">역할</Label>
              <Select
                id="c-role"
                value={createForm.role}
                onChange={(e) => setCreateForm((f) => ({ ...f, role: e.target.value }))}
              >
                {roleOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </Select>
            </div>
            {createError && <p className="text-label text-[#F04452]">{createError}</p>}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button color="blue" onClick={handleCreate} disabled={createLoading}>
            {createLoading && <Spinner size="sm" className="mr-2" />}
            {createLoading ? '저장 중...' : '생성'}
          </Button>
          <Button color="light" onClick={() => setCreateOpen(false)}>취소</Button>
        </ModalFooter>
      </Modal>

      {/* Edit Modal */}
      <Modal show={editOpen} size="md" onClose={() => setEditOpen(false)}>
        <ModalHeader>계정 수정</ModalHeader>
        <ModalBody>
          <div className="flex flex-col gap-4">
            <div>
              <Label htmlFor="e-username" className="mb-1.5 block text-label font-medium">아이디</Label>
              <TextInput
                id="e-username"
                placeholder="아이디"
                value={editForm.username}
                onChange={(e) => setEditForm((f) => ({ ...f, username: e.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="e-name" className="mb-1.5 block text-label font-medium">이름</Label>
              <TextInput
                id="e-name"
                placeholder="이름"
                value={editForm.name}
                onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="e-role" className="mb-1.5 block text-label font-medium">역할</Label>
              <Select
                id="e-role"
                value={editForm.role}
                onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))}
              >
                {roleOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="e-password" className="mb-1.5 block text-label font-medium">
                새 비밀번호 <span className="text-caption text-[#8B95A1]">(변경 시에만 입력)</span>
              </Label>
              <TextInput
                id="e-password"
                type="password"
                placeholder="새 비밀번호 (선택)"
                value={editForm.password}
                onChange={(e) => setEditForm((f) => ({ ...f, password: e.target.value }))}
              />
            </div>
            {editError && <p className="text-label text-[#F04452]">{editError}</p>}
          </div>
        </ModalBody>
        <ModalFooter>
          <div className="flex w-full items-center justify-between">
            {editTarget && editTarget.id !== currentUser?.id ? (
              <Button color="failure" size="sm" onClick={() => { setEditOpen(false); openDelete(editTarget) }}>
                삭제
              </Button>
            ) : <div />}
            <div className="flex items-center gap-2">
              <Button color="light" onClick={() => setEditOpen(false)}>취소</Button>
              <Button color="blue" onClick={handleEdit} disabled={editLoading}>
                {editLoading && <Spinner size="sm" className="mr-2" />}
                {editLoading ? '저장 중...' : '저장'}
              </Button>
            </div>
          </div>
        </ModalFooter>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={deleteOpen} size="md" popup onClose={() => setDeleteOpen(false)}>
        <ModalHeader />
        <ModalBody>
          <div className="flex flex-col items-center gap-4 py-2">
            <TriangleAlert className="h-10 w-10 text-[#FF9F00]" />
            <h3 className="text-heading font-semibold text-[#191F28] dark:text-white">
              계정 비활성화
            </h3>
            <p className="text-center text-body text-[#4E5968] dark:text-gray-300">
              <strong>{deleteTarget?.name}</strong> ({deleteTarget?.username}) 계정을 비활성화하시겠습니까?
            </p>
            <div className="flex gap-3">
              <Button
                color="failure"
                onClick={handleDelete}
                disabled={deleteLoading}
              >
                {deleteLoading && <Spinner size="sm" className="mr-2" />}
                {deleteLoading ? '처리 중...' : '비활성화'}
              </Button>
              <Button color="light" onClick={() => setDeleteOpen(false)}>취소</Button>
            </div>
          </div>
        </ModalBody>
      </Modal>
    </div>
  )
}
