// TimeReview.jsx - Main page component for hybrid time categorization
import React, { useState, useEffect, useCallback } from 'react';
import { safeFetchJson, API_BASE } from '@/lib/api';

// ============================================
// MAIN COMPONENT
// ============================================
export default function TimeReview() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(7);
  const [editingBlock, setEditingBlock] = useState(null);
  const [options, setOptions] = useState({ clients: [], taskTypes: [] });

  // Fetch grouped blocks
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [blocksData, clients, taskTypes] = await Promise.all([
        safeFetchJson(`${API_BASE}/blocks/grouped/?days=${days}`),
        safeFetchJson(`${API_BASE}/options/clients/`),
        safeFetchJson(`${API_BASE}/options/task-types/`),
      ]);
      setData(blocksData);
      setOptions({ clients, taskTypes });
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Handle block categorization
  const handleCategorize = async (blockId, categorization) => {
    try {
      await safeFetchJson(`${API_BASE}/blocks-api/${blockId}/categorize/`, {
        method: 'PATCH',
        body: JSON.stringify(categorization),
      });
      fetchData(); // Refresh data
      setEditingBlock(null);
    } catch (err) {
      alert('Error saving: ' + err.message);
    }
  };

  // Handle bulk categorization
  const handleBulkCategorize = async (blockIds, categorization) => {
    try {
      await safeFetchJson(`${API_BASE}/blocks-api/bulk/`, {
        method: 'POST',
        body: JSON.stringify({
          block_ids: blockIds,
          ...categorization,
        }),
      });
      fetchData();
    } catch (err) {
      alert('Error saving: ' + err.message);
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
        Error loading data: {error}
        <button onClick={fetchData} className="ml-4 text-blue-600 underline">
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Time Review</h1>
          <p className="text-gray-500 mt-1">
            Review and categorize your time blocks
          </p>
        </div>
        
        <div className="flex items-center gap-4">
          {/* Date Range Selector */}
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value={1}>Today</option>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
          
          <button
            onClick={fetchData}
            className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm font-medium"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      {data?.summary && (
        <SummaryStats summary={data.summary} />
      )}

      {/* Grouped Blocks */}
      <div className="space-y-4 mt-6">
        {data?.clients?.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            No time blocks found for this period
          </div>
        ) : (
          data?.clients?.map((client) => (
            <ClientSection
              key={client.client_id || 'uncategorized'}
              client={client}
              options={options}
              onEdit={setEditingBlock}
              onBulkCategorize={handleBulkCategorize}
            />
          ))
        )}
      </div>

      {/* Edit Modal */}
      {editingBlock && (
        <EditBlockModal
          block={editingBlock}
          options={options}
          onSave={handleCategorize}
          onClose={() => setEditingBlock(null)}
        />
      )}
    </div>
  );
}

// ============================================
// SUMMARY STATS
// ============================================
function SummaryStats({ summary }) {
  const uncategorizedPct = summary.total_blocks > 0
    ? Math.round((summary.uncategorized / summary.total_blocks) * 100)
    : 0;

  return (
    <div className="grid grid-cols-4 gap-4">
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="text-2xl font-bold text-gray-900">{summary.total_hours}h</div>
        <div className="text-sm text-gray-500">Total Hours</div>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="text-2xl font-bold text-gray-900">{summary.total_blocks}</div>
        <div className="text-sm text-gray-500">Time Blocks</div>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="text-2xl font-bold text-green-600">{summary.categorized}</div>
        <div className="text-sm text-gray-500">Categorized</div>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="text-2xl font-bold text-amber-600">{summary.uncategorized}</div>
        <div className="text-sm text-gray-500">
          Need Review {uncategorizedPct > 0 && `(${uncategorizedPct}%)`}
        </div>
      </div>
    </div>
  );
}

// ============================================
// CLIENT SECTION
// ============================================
function ClientSection({ client, options, onEdit, onBulkCategorize }) {
  const [isExpanded, setIsExpanded] = useState(true);
  const hours = (client.total_minutes / 60).toFixed(1);

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
      {/* Client Header */}
      <div
        className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between cursor-pointer hover:bg-gray-100"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <svg
            className={`w-5 h-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          
          <div className="flex items-center gap-2">
            <span className="font-semibold text-gray-900">{client.client_name}</span>
            {!client.client_id && (
              <span className="px-2 py-0.5 text-xs bg-amber-100 text-amber-700 rounded">
                Needs Assignment
              </span>
            )}
          </div>
        </div>
        
        <div className="text-sm font-medium text-gray-600">
          {hours} hours
        </div>
      </div>

      {/* Projects */}
      {isExpanded && (
        <div className="divide-y divide-gray-100">
          {Object.values(client.projects).map((project) => (
            <ProjectSection
              key={project.project_id || 'no-project'}
              project={project}
              clientId={client.client_id}
              options={options}
              onEdit={onEdit}
              onBulkCategorize={onBulkCategorize}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// PROJECT SECTION
// ============================================
function ProjectSection({ project, clientId, options, onEdit, onBulkCategorize }) {
  const [isExpanded, setIsExpanded] = useState(true);
  const hours = (project.total_minutes / 60).toFixed(1);

  return (
    <div className="pl-8 pr-4 py-2">
      {/* Project Header */}
      <div
        className="flex items-center justify-between py-2 cursor-pointer hover:bg-gray-50 rounded -ml-2 pl-2"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <svg
            className={`w-4 h-4 text-gray-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="font-medium text-gray-700">{project.project_name}</span>
        </div>
        <span className="text-sm text-gray-500">{hours}h</span>
      </div>

      {/* Task Types */}
      {isExpanded && (
        <div className="ml-6 space-y-2 mt-2">
          {Object.values(project.task_types).map((taskType) => (
            <TaskTypeSection
              key={taskType.task_type_id || 'uncategorized'}
              taskType={taskType}
              clientId={clientId}
              projectId={project.project_id}
              options={options}
              onEdit={onEdit}
              onBulkCategorize={onBulkCategorize}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// TASK TYPE SECTION
// ============================================
function TaskTypeSection({ taskType, clientId, projectId, options, onEdit, onBulkCategorize }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const hours = (taskType.total_minutes / 60).toFixed(1);
  const blockCount = taskType.blocks.length;

  // Get uncategorized blocks for bulk action
  const uncategorizedBlocks = taskType.blocks.filter(b => !b.is_categorized);

  return (
    <div className="bg-gray-50 rounded-lg p-3">
      {/* Task Type Header */}
      <div className="flex items-center justify-between">
        <div
          className="flex items-center gap-2 cursor-pointer flex-1"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: taskType.color }}
          />
          <span className="text-sm font-medium text-gray-700">
            {taskType.task_type_name}
          </span>
          <span className="text-xs text-gray-400">
            ({blockCount} {blockCount === 1 ? 'block' : 'blocks'})
          </span>
        </div>
        
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-600">{hours}h</span>
          
          {/* Bulk categorize button for uncategorized blocks */}
          {uncategorizedBlocks.length > 0 && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                // Quick categorize all blocks in this group
                const blockIds = uncategorizedBlocks.map(b => b.id);
                if (clientId && projectId && taskType.task_type_id) {
                  onBulkCategorize(blockIds, {
                    client_id: clientId,
                    project_id: projectId,
                    task_type_id: taskType.task_type_id,
                  });
                }
              }}
              className="text-xs px-2 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200"
              title="Confirm all blocks in this category"
            >
              ✓ Confirm All ({uncategorizedBlocks.length})
            </button>
          )}
          
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="text-gray-400 hover:text-gray-600"
          >
            <svg
              className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Individual Blocks */}
      {isExpanded && (
        <div className="mt-3 space-y-1">
          {taskType.blocks.map((block) => (
            <BlockRow
              key={block.id}
              block={block}
              onEdit={() => onEdit(block)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================
// BLOCK ROW
// ============================================
function BlockRow({ block, onEdit }) {
  const startTime = new Date(block.start).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
  const hours = ((block.minutes || 0) / 60).toFixed(1);

  // Truncate window title
  const title = block.window_title?.length > 60
    ? block.window_title.substring(0, 60) + '...'
    : block.window_title;

  return (
    <div className="flex items-center justify-between py-2 px-3 bg-white rounded text-sm hover:bg-gray-50 group">
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {/* Status indicator */}
        {block.is_categorized ? (
          <span className="text-green-500" title="Categorized">✓</span>
        ) : (
          <span className="text-amber-500" title="Needs review">○</span>
        )}
        
        <span className="text-gray-500 w-20 flex-shrink-0">{startTime}</span>
        
        <span className="text-gray-700 font-medium flex-shrink-0">
          {block.app_name || 'Unknown App'}
        </span>
        
        <span className="text-gray-500 truncate" title={block.window_title}>
          {title}
        </span>
      </div>
      
      <div className="flex items-center gap-3">
        <span className="font-medium text-gray-700">{hours}h</span>
        
        <button
          onClick={onEdit}
          className="opacity-0 group-hover:opacity-100 text-blue-600 hover:text-blue-800 text-sm transition-opacity"
        >
          Edit
        </button>
      </div>
    </div>
  );
}

// ============================================
// EDIT MODAL
// ============================================
function EditBlockModal({ block, options, onSave, onClose }) {
  const [formData, setFormData] = useState({
    client_id: '',
    project_id: '',
    task_type_id: '',
    notes: '',
  });
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(false);

  // Load projects when client changes
  useEffect(() => {
    if (formData.client_id) {
      safeFetchJson(`${API_BASE}/options/projects/${formData.client_id}/`)
        .then(setProjects)
        .catch(console.error);
    } else {
      setProjects([]);
    }
  }, [formData.client_id]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    
    const data = {};
    if (formData.client_id) data.client_id = Number(formData.client_id);
    if (formData.project_id) data.project_id = Number(formData.project_id);
    if (formData.task_type_id) data.task_type_id = Number(formData.task_type_id);
    if (formData.notes) data.notes = formData.notes;
    
    await onSave(block.id, data);
    setLoading(false);
  };

  const startTime = new Date(block.start).toLocaleString();
  const hours = ((block.minutes || 0) / 60).toFixed(1);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-900">Edit Time Block</h3>
          <p className="text-sm text-gray-500 mt-1">
            {startTime} • {hours} hours
          </p>
        </div>

        {/* Block Info */}
        <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
          <div className="text-sm">
            <div className="font-medium text-gray-700">{block.app_name}</div>
            <div className="text-gray-500 mt-1 break-words">{block.window_title}</div>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Client */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Client
            </label>
            <select
              value={formData.client_id}
              onChange={(e) => setFormData({
                ...formData,
                client_id: e.target.value,
                project_id: '', // Reset project
              })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="">Select client...</option>
              {options.clients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.name} {client.code && `(${client.code})`}
                </option>
              ))}
            </select>
          </div>

          {/* Project */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Project / Engagement
            </label>
            <select
              value={formData.project_id}
              onChange={(e) => setFormData({ ...formData, project_id: e.target.value })}
              disabled={!formData.client_id}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100 disabled:text-gray-400"
            >
              <option value="">Select project...</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            {formData.client_id && projects.length === 0 && (
              <p className="text-sm text-gray-500 mt-1">
                No projects found. <a href="/settings/projects" className="text-blue-600">Add one?</a>
              </p>
            )}
          </div>

          {/* Task Type */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Task Type
            </label>
            <select
              value={formData.task_type_id}
              onChange={(e) => setFormData({ ...formData, task_type_id: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="">Select task type...</option>
              {options.taskTypes.map((tt) => (
                <option key={tt.id} value={tt.id}>
                  {tt.name} {!tt.is_billable && '(Non-billable)'}
                </option>
              ))}
            </select>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Notes (optional)
            </label>
            <textarea
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              rows={3}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Add context about this time block..."
            />
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 font-medium"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium disabled:opacity-50"
            >
              {loading ? 'Saving...' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}