import React, { useState } from 'react';
import Login from './components/Login.js';
import Navbar from './components/Navbar.js';
import Uploader from './components/Uploader.js';
import Dashboard from './components/Dashboard.js';
import Escalation from './components/Escalation.js';

import type { Role, User } from './types.js';
import { API_BASE_URL } from './config.js';



function App() {
  const [user, setUser] = useState<User | null>(null);
  const [currentView, setCurrentView] = useState<string>('dashboard');

  const handleLogin = async (email: string, password: string): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE_URL}/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      if (response.ok) {
        const userData: User = await response.json();
        setUser(userData);

        if (userData.role === 'uploader') {
          // Always go to uploader view, it handles its own internal routing/status
          setCurrentView('uploader');
        } else {
          setCurrentView('dashboard');
        }
        return true;
      }
      return false;
    } catch (error) {
      console.error('Login failed:', error);
      return false;
    }
  };

  const handleLogout = () => {
    setUser(null);
  };

  const handleViewChange = (view: string) => {
    setCurrentView(view);
  };

  if (!user) {
    return <Login onLogin={handleLogin} />;
  }

  return (
    <div className="app-container">
      <Navbar
        role={user.role}
        onLogout={handleLogout}
        currentView={currentView}
        onViewChange={handleViewChange}
        escalationCount={3}
      />

      {currentView === 'uploader' && (
        <Uploader
          userId={user.user_id}
          initialStatus={user.status}
          initialSubmissionId={user.caseId}
          onComplete={() => { }} // No longer need to switch views
        />
      )}
      {currentView === 'dashboard' && <Dashboard onEscalate={() => handleViewChange('escalation')} />}
      {currentView === 'escalation' && <Escalation />}
    </div>
  );
}

export default App;
