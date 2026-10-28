// Global channel for the 3D robot assistant. Views dispatch lifecycle facts here;
// the adapter inside RobotAssistant turns them (plus 'toast' and 'theme-change')
// into robot states. Plain window CustomEvents keep this dependency-free and
// match the project's existing toast / theme event patterns.
export const ROBOT_EVENT = 'robot-assistant'

export function robotEvent(type, payload = {}) {
  window.dispatchEvent(new CustomEvent(ROBOT_EVENT, { detail: { type, payload } }))
}

// Lifecycle facts dispatched by Chat.vue (conversation / goal streams):
//   task:submitted {id, title}          user sent a task, stream not started yet
//   task:working   {id, goal?}          agent is executing (also used for restore)
//   task:tool      {id, tool, agent}    a tool is being called
//   task:collab    {id, agent}          multi-agent collaboration running
//   task:waiting   {id}                 agent waits for user confirmation
//   task:resolved  {id}                 user answered the confirmation
//   task:done      {id, question}       finished successfully
//   task:error     {id, message}        execution failed
//   runtime:snapshot {tasks:[{id,title,phase}]}  authoritative state after reload
