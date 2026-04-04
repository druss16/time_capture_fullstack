// components/IndividualReturnsSection.tsx
//
// Renders individual tax return blocks as named sub-buckets in the
// Daily Review / Summary view. Mirrors the existing client card pattern
// but groups by taxpayer_bucket instead of client.
//
// PLACEMENT: Render this component at the BOTTOM of the Summary tab
// client list, after all real client cards. It only shows when
// individualReturnBlocks.length > 0.
//
// PROPS:
//   blocks           — array of Block objects with taxpayer_name set
//   date             — current date string ("04/04/2026")
//   onMoveBlock      — same handler used by client cards
//   onMoveAll        — same bulk-move handler
//
// DATA CONTRACT (what Block must have for this component):
//   block.taxpayer_name      — "Wood, Michael" | "Wood, Michael (1)"
//   block.taxpayer_id_hash   — "a3f9c2b18e44"
//   block.tax_return_type    — "1040" | "1065" | etc.
//   block.ai_category        — "Tax Preparation"
//   block.category_hours     — { "Tax Preparation": 0.5 }
//   block.duration_minutes   — number
//   block.window_title       — original title for display

import React, { useState, useMemo } from 'react'
import { ChevronDown, ChevronRight, FileText, MoveRight } from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Block {
  id: number
  window_title: string
  taxpayer_name: string
  taxpayer_id_hash: string
  tax_return_type: string
  ai_category: string
  category_hours: Record<string, number>
  duration_minutes: number
  is_categorized: boolean
}

interface TaxpayerGroup {
  display_name: string
  hash: string
  return_types: string[]
  blocks: Block[]
  total_minutes: number
  billable_minutes: number
}

interface Props {
  blocks: Block[]
  date: string
  onMoveBlock?: (blockId: number) => void
  onMoveAll?: (blockIds: number[]) => void
}

// ---------------------------------------------------------------------------
// Return type badge color mapping
// ---------------------------------------------------------------------------

const RETURN_TYPE_COLORS: Record<string, string> = {
  '1040':  'bg-blue-100 text-blue-700',
  '1065':  'bg-purple-100 text-purple-700',
  '1120':  'bg-orange-100 text-orange-700',
  '1120S': 'bg-orange-100 text-orange-700',
  '990':   'bg-green-100 text-green-700',
  '1041':  'bg-pink-100 text-pink-700',
}

function ReturnTypeBadge({ type }: { type: string }) {
  const colors = RETURN_TYPE_COLORS[type] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${colors}`}>
      {type}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Duration formatting (matches existing TimeTracker display)
// ---------------------------------------------------------------------------

function fmtMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes}m`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m === 0 ? `${h}h` : `${h}h ${m}m`
}

// ---------------------------------------------------------------------------
// Single taxpayer row inside the section
// ---------------------------------------------------------------------------

function TaxpayerCard({
  group,
  onMoveBlock,
  onMoveAll,
}: {
  group: TaxpayerGroup
  onMoveBlock?: (blockId: number) => void
  onMoveAll?: (blockIds: number[]) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const blockIds = group.blocks.map(b => b.id)

  return (
    <div className="border border-gray-100 rounded-lg mb-2 overflow-hidden">
      {/* Header row */}
      <div
        className="flex items-center gap-2 px-4 py-3 bg-gray-50 cursor-pointer hover:bg-gray-100 select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="text-gray-400 w-4 flex-shrink-0">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>

        <FileText size={14} className="text-gray-400 flex-shrink-0" />

        <span className="font-medium text-gray-800 flex-1 text-sm">
          {group.display_name}
        </span>

        {/* Return type badges */}
        <div className="flex gap-1 flex-shrink-0">
          {group.return_types.map(rt => (
            <ReturnTypeBadge key={rt} type={rt} />
          ))}
        </div>

        {/* Time totals */}
        <div className="flex items-center gap-3 flex-shrink-0 ml-2">
          {group.billable_minutes > 0 && (
            <div className="text-right">
              <span className="text-sm font-semibold text-emerald-600">
                {fmtMinutes(group.billable_minutes)}
              </span>
              <span className="text-xs text-gray-400 ml-1">BILLABLE</span>
            </div>
          )}
          {group.total_minutes - group.billable_minutes > 0 && (
            <div className="text-right">
              <span className="text-sm font-semibold text-gray-500">
                {fmtMinutes(group.total_minutes - group.billable_minutes)}
              </span>
              <span className="text-xs text-gray-400 ml-1">NON-BILL</span>
            </div>
          )}
        </div>

        {/* Bulk move */}
        {onMoveAll && (
          <button
            className="text-xs text-gray-400 hover:text-gray-600 flex-shrink-0 ml-2"
            onClick={e => { e.stopPropagation(); onMoveAll(blockIds) }}
          >
            Move all
          </button>
        )}
      </div>

      {/* Block rows */}
      {expanded && (
        <div className="divide-y divide-gray-50">
          {group.blocks.map(block => (
            <div
              key={block.id}
              className="flex items-center gap-3 px-8 py-2 hover:bg-gray-50 group"
            >
              {/* Category pill */}
              <span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded flex-shrink-0">
                {block.ai_category || 'Tax Preparation'}
              </span>

              {/* Title */}
              <span className="text-sm text-gray-700 flex-1 truncate">
                {block.window_title}
              </span>

              {/* Duration */}
              <span className="text-sm text-gray-500 flex-shrink-0">
                ({fmtMinutes(block.duration_minutes)})
              </span>

              {/* Move action */}
              {onMoveBlock && (
                <button
                  className="text-xs text-gray-300 hover:text-gray-500 opacity-0 group-hover:opacity-100 flex-shrink-0"
                  onClick={() => onMoveBlock(block.id)}
                >
                  click to move
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main section component
// ---------------------------------------------------------------------------

export function IndividualReturnsSection({ blocks, date, onMoveBlock, onMoveAll }: Props) {
  const [sectionExpanded, setSectionExpanded] = useState(true)

  // Group blocks by taxpayer_id_hash
  const groups = useMemo<TaxpayerGroup[]>(() => {
    const map = new Map<string, TaxpayerGroup>()

    for (const block of blocks) {
      if (!block.taxpayer_name || !block.taxpayer_id_hash) continue

      const key = block.taxpayer_id_hash
      if (!map.has(key)) {
        map.set(key, {
          display_name: block.taxpayer_name,
          hash: block.taxpayer_id_hash,
          return_types: [],
          blocks: [],
          total_minutes: 0,
          billable_minutes: 0,
        })
      }
      const group = map.get(key)!
      group.blocks.push(block)
      group.total_minutes += block.duration_minutes || 0

      // Count billable minutes (Tax Preparation is always billable)
      const isBillable = block.ai_category === 'Tax Preparation'
        || block.ai_category === 'Tax Review'
        || block.ai_category === 'Tax Research'
      if (isBillable) {
        group.billable_minutes += block.duration_minutes || 0
      }

      // Track unique return types
      if (block.tax_return_type && !group.return_types.includes(block.tax_return_type)) {
        group.return_types.push(block.tax_return_type)
      }
    }

    // Sort groups by total time descending
    return Array.from(map.values()).sort((a, b) => b.total_minutes - a.total_minutes)
  }, [blocks])

  if (groups.length === 0) return null

  const totalMinutes    = groups.reduce((s, g) => s + g.total_minutes, 0)
  const billableMinutes = groups.reduce((s, g) => s + g.billable_minutes, 0)
  const totalBlocks     = blocks.length

  return (
    <div className="mb-4">
      {/* Section header — styled like a client card but amber/gold accent */}
      <div
        className="flex items-center gap-2 px-4 py-4 bg-white border border-gray-200 rounded-xl cursor-pointer hover:bg-gray-50 select-none"
        style={{ borderLeft: '4px solid #f59e0b' }}
        onClick={() => setSectionExpanded(e => !e)}
      >
        <span className="text-gray-400 w-4 flex-shrink-0">
          {sectionExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </span>

        <div className="flex-1">
          <span className="font-bold text-gray-800">Individual Returns</span>
          <span className="text-sm text-gray-400 ml-2">
            {groups.length} taxpayer{groups.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Section totals */}
        <div className="flex items-center gap-4">
          {billableMinutes > 0 && (
            <div className="text-right">
              <div className="text-base font-bold text-emerald-600">
                {fmtMinutes(billableMinutes)}
              </div>
              <div className="text-xs text-gray-400">BILLABLE</div>
            </div>
          )}
          {totalMinutes - billableMinutes > 0 && (
            <div className="text-right">
              <div className="text-base font-bold text-gray-500">
                {fmtMinutes(totalMinutes - billableMinutes)}
              </div>
              <div className="text-xs text-gray-400">NON-BILL</div>
            </div>
          )}
        </div>
      </div>

      {/* Taxpayer cards */}
      {sectionExpanded && (
        <div className="mt-2 pl-2">
          {groups.map(group => (
            <TaxpayerCard
              key={group.hash}
              group={group}
              onMoveBlock={onMoveBlock}
              onMoveAll={onMoveAll}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default IndividualReturnsSection
