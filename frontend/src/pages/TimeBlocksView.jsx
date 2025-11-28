// TimeBlocksView.jsx

import React, { useState } from 'react';

const TimeBlocksView = ({ timeBlocks, clients, onUpdate }) => {
  const [groupBy, setGroupBy] = useState('client-project'); // or 'task-type' or 'date'
  
  // Group blocks by Client → Project → Task Type
  const groupedBlocks = groupByClientProject(timeBlocks);
  
  return (
    <div className="p-6">
      {/* View Controls */}
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-2xl font-bold">Time Review</h2>
        <select 
          value={groupBy} 
          onChange={(e) => setGroupBy(e.target.value)}
          className="border rounded px-3 py-2"
        >
          <option value="client-project">By Client → Project</option>
          <option value="task-type">By Task Type</option>
          <option value="date">By Date</option>
        </select>
      </div>

      {/* Grouped Time Blocks */}
      {Object.entries(groupedBlocks).map(([clientName, clientData]) => (
        <ClientSection 
          key={clientData.client.id}
          client={clientData.client}
          projects={clientData.projects}
          totalHours={clientData.totalHours}
          onUpdate={onUpdate}
        />
      ))}
    </div>
  );
};

const ClientSection = ({ client, projects, totalHours, onUpdate }) => {
  const [isExpanded, setIsExpanded] = useState(true);
  
  return (
    <div className="mb-6 border rounded-lg bg-white shadow">
      {/* Client Header */}
      <div 
        className="p-4 bg-gray-50 border-b cursor-pointer flex items-center justify-between"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <svg className={`w-5 h-5 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
            <path d="M9 6l6 6-6 6" />
          </svg>
          <h3 className="text-lg font-semibold">{client.name}</h3>
          <span className="text-sm text-gray-500">({totalHours.toFixed(1)} hrs)</span>
        </div>
      </div>

      {/* Projects */}
      {isExpanded && (
        <div className="p-4">
          {Object.entries(projects).map(([projectName, projectData]) => (
            <ProjectSection
              key={projectData.project.id}
              project={projectData.project}
              timeBlocks={projectData.blocks}
              onUpdate={onUpdate}
            />
          ))}
        </div>
      )}
    </div>
  );
};

const ProjectSection = ({ project, timeBlocks, onUpdate }) => {
  const [isExpanded, setIsExpanded] = useState(true);
  
  // Group by task type within project
  const byTaskType = timeBlocks.reduce((acc, block) => {
    const taskName = block.task_type?.name || 'Uncategorized';
    if (!acc[taskName]) acc[taskName] = [];
    acc[taskName].push(block);
    return acc;
  }, {});
  
  const projectTotal = timeBlocks.reduce((sum, b) => sum + (b.duration_minutes / 60), 0);
  
  return (
    <div className="mb-4 ml-6 border-l-2 border-blue-200 pl-4">
      {/* Project Header */}
      <div 
        className="flex items-center justify-between cursor-pointer py-2"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-700">{project.name}</span>
          <span className="text-sm text-gray-500">({projectTotal.toFixed(1)} hrs)</span>
        </div>
      </div>

      {/* Task Types */}
      {isExpanded && (
        <div className="mt-2 space-y-2">
          {Object.entries(byTaskType).map(([taskName, blocks]) => (
            <TaskTypeSection
              key={taskName}
              taskName={taskName}
              blocks={blocks}
              onUpdate={onUpdate}
            />
          ))}
        </div>
      )}
    </div>
  );
};

const TaskTypeSection = ({ taskName, blocks, onUpdate }) => {
  const taskTotal = blocks.reduce((sum, b) => sum + (b.duration_minutes / 60), 0);
  
  return (
    <div className="bg-gray-50 rounded p-3">
      {/* Task Type Header */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-600">{taskName}</span>
        <span className="text-sm text-gray-500">{taskTotal.toFixed(1)} hrs</span>
      </div>

      {/* Individual Time Blocks */}
      <div className="space-y-1">
        {blocks.map(block => (
          <TimeBlockRow 
            key={block.id}
            block={block}
            onUpdate={onUpdate}
          />
        ))}
      </div>
    </div>
  );
};

const TimeBlockRow = ({ block, onUpdate }) => {
  const [isEditing, setIsEditing] = useState(false);
  
  const duration = (block.duration_minutes / 60).toFixed(1);
  const startTime = new Date(block.start_time).toLocaleTimeString('en-US', { 
    hour: 'numeric', 
    minute: '2-digit' 
  });
  
  return (
    <div className="flex items-center justify-between py-2 px-3 hover:bg-white rounded text-sm">
      <div className="flex-1">
        <span className="text-gray-600">{startTime}</span>
        <span className="mx-2">•</span>
        <span className="text-gray-800">{block.app_name}</span>
        {block.notes && (
          <span className="ml-2 text-gray-500 italic">"{block.notes}"</span>
        )}
      </div>
      
      <div className="flex items-center gap-3">
        <span className="font-medium">{duration}h</span>
        
        {/* Edit Button */}
        <button
          onClick={() => setIsEditing(true)}
          className="text-blue-600 hover:text-blue-800"
        >
          Edit
        </button>
      </div>
      
      {/* Edit Modal */}
      {isEditing && (
        <EditTimeBlockModal
          block={block}
          onSave={(updated) => {
            onUpdate(updated);
            setIsEditing(false);
          }}
          onCancel={() => setIsEditing(false)}
        />
      )}
    </div>
  );
};