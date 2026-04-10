// src/pages/settings/TeamTab.tsx
import { useEffect, useState } from 'react';
import { Users, UserPlus, RefreshCw, Mail, Trash2, Plus, Check, X } from 'lucide-react';
import { cn, getRoleColor } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import { getUserDisplayName } from './types';
import type { TeamMember } from './types';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

interface Props {
  members: TeamMember[];
  currentUserId: number | null;
  currentUserRole: string;
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

export default function TeamTab({ members, currentUserId, currentUserRole, onRefresh, onSuccess, onError }: Props) {
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviting, setInviting] = useState(false);
  const [seatInfo, setSeatInfo] = useState<{
    seat_count: number; members: number; pending_invites: number;
    seats_available: number; can_invite: boolean;
  } | null>(null);

  useEffect(() => {
    safeFetchJson<any>(`${API_BASE}/settings/seats/`)
      .then(data => setSeatInfo(data))
      .catch(() => {});
  }, [members]);

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    try {
      const response = await safeFetchJson<any>(`${API_BASE}/settings/team/invite/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: inviteEmail }),
      });
      if (response.temp_password && !response.email_sent) {
        alert(`User created!\n\nUsername: ${response.username}\nTemp Password: ${response.temp_password}\n\nPlease share these credentials with the user.`);
      }
      onSuccess(response.email_sent ? 'Invitation sent' : 'User created (share credentials manually)');
      setInviteEmail('');
      setShowInvite(false);
      onRefresh();
      const seatData = await safeFetchJson<any>(`${API_BASE}/settings/seats/`);
      setSeatInfo(seatData);
    } catch (err: any) {
      if (err?.upgrade_required) {
        onError(`No seats available. You have ${err.seat_count} seats with ${err.current_members} members.`);
      } else {
        onError(err?.message || 'Failed to invite');
      }
    } finally {
      setInviting(false);
    }
  };

  const handleRemove = async (userId: number, username: string) => {
    if (!confirm(`Remove ${username} from the team?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/team/${userId}/`, { method: 'DELETE' });
      onSuccess('Team member removed');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to remove');
    }
  };

  const formatLastSeen = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const getRoleBadge = (role: string) => {
    switch (role) {
      case 'owner':   return 'bg-purple-100 text-purple-800';
      case 'admin':   return 'bg-blue-100 text-blue-800';
      case 'manager': return 'bg-emerald-100 text-emerald-800';
      default:        return 'bg-slate-100 text-slate-700';
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Users className="w-5 h-5 text-primary" />
          Team Members
          <span className="text-sm font-semibold text-slate-400">({members.length})</span>
        </h2>
        <button
          onClick={() => setShowInvite(true)}
          disabled={seatInfo !== null && !seatInfo.can_invite}
          className={cn(
            'flex items-center gap-1.5 px-3 py-2 rounded-lg font-semibold text-sm transition-all',
            seatInfo && !seatInfo.can_invite
              ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
              : 'bg-primary text-white hover:opacity-90'
          )}
        >
          <UserPlus className="w-3.5 h-3.5" /> Invite Member
        </button>
      </div>

      {/* Seat usage bar */}
      {seatInfo && seatInfo.seat_count > 0 && (
        <div className="mb-5 p-4 bg-slate-50 border border-border/60 rounded-xl">
          <div className="flex items-center justify-between mb-2">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Team Seats</p>
              <p className="text-xl font-extrabold text-slate-900">
                {seatInfo.members} <span className="text-slate-400 font-medium text-sm">/ {seatInfo.seat_count} used</span>
              </p>
            </div>
            {!seatInfo.can_invite && (
              <a href="/account/billing" className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white font-semibold rounded-lg hover:opacity-90 text-sm">
                <Plus className="w-3.5 h-3.5" /> Add Seats
              </a>
            )}
          </div>
          <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all',
                seatInfo.members >= seatInfo.seat_count ? 'bg-red-500'
                : seatInfo.members >= seatInfo.seat_count * 0.8 ? 'bg-amber-500'
                : 'bg-emerald-500'
              )}
              style={{ width: `${Math.min(100, (seatInfo.members / seatInfo.seat_count) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Invite form */}
      {showInvite && (
        <div className="mb-5 p-4 bg-slate-50 border border-dashed border-slate-300 rounded-xl">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">Invite Team Member</p>
          <div className="flex gap-2">
            <input
              type="email" value={inviteEmail}
              onChange={e => setInviteEmail(e.target.value)}
              placeholder="email@company.com"
              className="flex-1 border border-border/60 rounded-lg px-3 py-2 text-sm font-medium text-slate-900 focus:border-primary focus:outline-none transition-all bg-white"
            />
            <button
              onClick={handleInvite} disabled={inviting || !inviteEmail.trim()}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white rounded-lg font-semibold text-sm hover:opacity-90 disabled:opacity-50 transition-all"
            >
              {inviting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Mail className="w-3.5 h-3.5" />}
              Send
            </button>
            <button onClick={() => setShowInvite(false)} className="px-3 py-2 border border-border/60 rounded-lg font-semibold text-sm text-slate-600 hover:bg-slate-100 transition-all">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="border border-border/60 rounded-xl overflow-hidden">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-border/60 bg-slate-50/80">
              <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">User</th>
              <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Email</th>
              <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Role</th>
              <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Last Active</th>
              <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {members.length === 0 ? (
              <tr><td colSpan={5} className="text-center py-10 text-slate-400">No team members yet</td></tr>
            ) : members.map(member => {
              const isCurrentUser = member.id === currentUserId;
              const displayName = getUserDisplayName(member);
              return (
                <tr key={member.id} className="hover:bg-slate-50/60 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                        <span className="text-xs font-bold text-primary">{displayName[0].toUpperCase()}</span>
                      </div>
                      <div>
                        <p className="font-semibold text-slate-800 text-sm">
                          {displayName}
                          {isCurrentUser && <span className="ml-2 text-xs text-slate-400">(you)</span>}
                        </p>
                        <p className="text-xs text-slate-400">@{member.username}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">{member.email || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={cn('text-xs px-2 py-0.5 rounded-full font-semibold', getRoleBadge(member.role))}>
                      {member.role.charAt(0).toUpperCase() + member.role.slice(1)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-400">{formatLastSeen(member.last_login)}</td>
                  <td className="px-4 py-3 text-right">
                    {!isCurrentUser && member.role !== 'owner' && (
                      <button
                        onClick={() => handleRemove(member.id, member.username)}
                        className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}