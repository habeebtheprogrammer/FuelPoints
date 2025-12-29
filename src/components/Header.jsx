import { useState } from 'react';

function Header({ theme, toggleTheme }) {
  return (
    <header className="admin-header">
      <div className="logo">
        <span className="logo-text">Birdies</span>
        <h1>Admin Portal</h1>
      </div>
      <button className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
        {theme === 'light' ? '🌙' : '☀️'}
      </button>
    </header>
  );
}

export default Header;
