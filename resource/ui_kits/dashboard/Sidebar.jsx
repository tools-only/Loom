/* global React */

function Sidebar({ active = 'overview', onNav = () => {} }) {
  const items = [
    { id: 'overview', label: 'Overview', icon: 'ph-house' },
    { id: 'reports',  label: 'Reports',  icon: 'ph-file-text', count: 3 },
    { id: 'metrics',  label: 'Metrics',  icon: 'ph-chart-bar' },
    { id: 'sources',  label: 'Sources',  icon: 'ph-database' },
  ];
  const settings = [
    { id: 'agents',   label: 'Agents',   icon: 'ph-sparkle' },
    { id: 'team',     label: 'Team',     icon: 'ph-users-three' },
    { id: 'settings', label: 'Settings', icon: 'ph-gear-six' },
  ];

  const renderItem = (it) => (
    <div
      key={it.id}
      className={`dk-nav-item ${active === it.id ? 'active' : ''}`}
      onClick={() => onNav(it.id)}
    >
      <i className={`ph-bold ${it.icon}`}></i>
      <span>{it.label}</span>
      {it.count && <span className="count">{it.count}</span>}
    </div>
  );

  return (
    <aside className="dk-sidebar">
      <div className="dk-brand">
        <img src="../../assets/logo-mark.svg" alt="" />
        <span>bloom</span>
      </div>
      <nav className="dk-nav">
        <div className="dk-nav-section">Workspace</div>
        {items.map(renderItem)}
        <div className="dk-nav-section">Account</div>
        {settings.map(renderItem)}
      </nav>
      <div className="dk-sidebar-user">
        <div className="dk-sidebar-user-av"></div>
        <div className="dk-sidebar-user-meta">
          <span className="dk-sidebar-user-name">Sandra Glam</span>
          <span className="dk-sidebar-user-sub">Free plan</span>
        </div>
      </div>
    </aside>
  );
}

window.Sidebar = Sidebar;
