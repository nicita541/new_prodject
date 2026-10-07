import { NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { api } from '../../api/client';

export function Sidebar() {
  const [healthReady, setHealthReady] = useState(false);
  const [label, setLabel] = useState('Подключение...');

  useEffect(() => {
    let mounted = true;
    const fetchHealth = async () => {
      try {
        const data = await api.getHealth();
        if (!mounted) return;
        setHealthReady(data.ready);
        if (data.busy) {
          setLabel('Монтаж выполняется');
        } else if (data.ready) {
          setLabel('Система готова · локально'); // Might need to update for deepseek check later
        } else {
          setLabel('Требуется настройка');
        }
      } catch (err) {
        if (!mounted) return;
        setLabel('Ошибка подключения');
      }
    };
    
    fetchHealth();
    const timer = setInterval(fetchHealth, 5000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);

  return (
    <aside className="sidebar">
      <NavLink to="/projects" className="brand" aria-label="Кадр, проекты">
        <span className="brand-mark" aria-hidden="true">К</span>
        КАДР STUDIO
      </NavLink>
      
      <nav className="nav-menu" aria-label="Главное меню">
        <NavLink 
          to="/projects" 
          className={({ isActive }) => `nav-link ${isActive ? 'nav-active' : ''}`}
        >
          Проекты
        </NavLink>
        <NavLink 
          to="/trash" 
          className={({ isActive }) => `nav-link ${isActive ? 'nav-active' : ''}`}
        >
          Корзина
        </NavLink>
      </nav>
      
      <span id="connection" className={`status-pill ${healthReady ? 'ready' : ''}`}>
        <span className="status-dot"></span>
        <span id="connection-label">{label}</span>
      </span>
    </aside>
  );
}
