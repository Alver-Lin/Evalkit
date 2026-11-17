import type { ThemeConfig } from 'ant-design-vue/es/config-provider/context'

/** Keep in sync with styles/global.css semantic tokens. */
export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#0f766e',
    colorInfo: '#0f766e',
    colorSuccess: '#16a34a',
    colorError: '#dc2626',
    colorWarning: '#a16207',
    colorText: '#111827',
    colorTextSecondary: '#4b5565',
    colorBorder: 'rgba(17, 24, 39, 0.08)',
    colorBgContainer: '#ffffff',
    colorBgLayout: '#f5f7fa',
    borderRadius: 8,
    fontFamily: '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif',
    fontSize: 14,
    controlHeight: 32,
    wireframe: false,
  },
  components: {
    Button: {
      borderRadius: 8,
      controlHeight: 32,
      fontWeight: 500,
    },
    Table: {
      headerBg: '#f5f7fa',
      headerColor: '#4b5565',
      rowHoverBg: '#eceff4',
    },
    Tabs: {
      titleFontSize: 14,
      horizontalItemPadding: '10px 0',
      horizontalMargin: '0 0 16px 0',
    },
    Menu: {
      itemHeight: 36,
      itemBorderRadius: 8,
      itemMarginInline: 8,
      iconSize: 16,
    },
    Drawer: {
      paddingLG: 20,
    },
  },
}
