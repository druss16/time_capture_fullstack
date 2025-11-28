// EditTimeBlockModal.jsx

const EditTimeBlockModal = ({ block, onSave, onCancel }) => {
  const [formData, setFormData] = useState({
    client_id: block.client?.id || '',
    project_id: block.project?.id || '',
    task_type_id: block.task_type?.id || '',
    notes: block.notes || '',
    is_billable: block.is_billable,
  });
  
  const [clients, setClients] = useState([]);
  const [projects, setProjects] = useState([]);
  const [taskTypes, setTaskTypes] = useState([]);
  
  useEffect(() => {
    // Load clients, projects, task types from API
    fetchClients().then(setClients);
    fetchTaskTypes().then(setTaskTypes);
  }, []);
  
  // In EditBlockModal, update the useEffect:
  useEffect(() => {
    if (formData.client_id) {
      apiRequest(`/api/options/projects/${formData.client_id}/`)
        .then(setProjects)
        .catch(console.error);
    } else {
      setProjects([]);
    }
  }, [formData.client_id]);
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    const updated = await fetch(`/api/timeblocks/${block.id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...formData,
        is_reviewed: true,
      }),
    }).then(r => r.json());
    
    onSave(updated);
  };
  
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-md w-full">
        <h3 className="text-lg font-semibold mb-4">Edit Time Block</h3>
        
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Client Dropdown */}
          <div>
            <label className="block text-sm font-medium mb-1">Client</label>
            <select
              value={formData.client_id}
              onChange={(e) => setFormData({
                ...formData, 
                client_id: e.target.value,
                project_id: '', // Reset project when client changes
              })}
              className="w-full border rounded px-3 py-2"
              required
            >
              <option value="">Select client...</option>
              {clients.map(client => (
                <option key={client.id} value={client.id}>
                  {client.name}
                </option>
              ))}
            </select>
          </div>
          
          {/* Project Dropdown (filtered by client) */}
          <div>
            <label className="block text-sm font-medium mb-1">Project/Engagement</label>
            <select
              value={formData.project_id}
              onChange={(e) => setFormData({...formData, project_id: e.target.value})}
              className="w-full border rounded px-3 py-2"
              disabled={!formData.client_id}
              required
            >
              <option value="">Select project...</option>
              {projects.map(project => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            
            {/* Quick Add Project */}
            {formData.client_id && (
              <button
                type="button"
                onClick={() => {/* Open quick-add modal */}}
                className="text-sm text-blue-600 mt-1"
              >
                + Add new project
              </button>
            )}
          </div>
          
          {/* Task Type Dropdown */}
          <div>
            <label className="block text-sm font-medium mb-1">Task Type</label>
            <select
              value={formData.task_type_id}
              onChange={(e) => setFormData({...formData, task_type_id: e.target.value})}
              className="w-full border rounded px-3 py-2"
              required
            >
              <option value="">Select task type...</option>
              {taskTypes.map(taskType => (
                <option key={taskType.id} value={taskType.id}>
                  {taskType.name}
                </option>
              ))}
            </select>
          </div>
          
          {/* Billable Toggle */}
          <div className="flex items-center">
            <input
              type="checkbox"
              id="billable"
              checked={formData.is_billable}
              onChange={(e) => setFormData({...formData, is_billable: e.target.checked})}
              className="mr-2"
            />
            <label htmlFor="billable" className="text-sm">Billable</label>
          </div>
          
          {/* Notes */}
          <div>
            <label className="block text-sm font-medium mb-1">Notes (optional)</label>
            <textarea
              value={formData.notes}
              onChange={(e) => setFormData({...formData, notes: e.target.value})}
              className="w-full border rounded px-3 py-2"
              rows="3"
              placeholder="Add context about this time block..."
            />
          </div>
          
          {/* Actions */}
          <div className="flex gap-3 pt-4">
            <button
              type="button"
              onClick={onCancel}
              className="flex-1 px-4 py-2 border rounded hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              Save
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};