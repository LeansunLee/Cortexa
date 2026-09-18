// Preferences belong to an account in this browser, independently of its workspace.
let currentUser
export function preferenceKey(key, storage = localStorage) {
  let id = currentUser
  if (id === undefined) {
    try { id = storage.getItem('personalization-user') } catch { /* Storage unavailable. */ }
  }
  return id ? `${key}:user:${id}` : key
}

export function activatePreferences(userId, storage = localStorage) {
  currentUser = String(userId)
  try {
    // Assign legacy browser preferences only to the first account after migration.
    if (!storage.getItem('personalization-migrated')) {
      for (const key of ['theme-color', 'ui-appearance']) {
        const saved = storage.getItem(key) || (key === 'theme-color' ? storage.getItem('themeColor') : null)
        if (saved && !storage.getItem(preferenceKey(key, storage))) storage.setItem(preferenceKey(key, storage), saved)
      }
      storage.setItem('personalization-migrated', currentUser)
    }
    storage.setItem('personalization-user', currentUser)
  } catch { /* An unavailable browser store must not prevent login. */ }
}
