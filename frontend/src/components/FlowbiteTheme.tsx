import { ThemeProvider as FlowbiteThemeProvider } from 'flowbite-react'

const customTheme = {
  card: {
    root: {
      base: 'flex rounded-2xl bg-white dark:bg-[#1E1E24]',
      children: 'flex h-full flex-col gap-4 p-5',
    },
  },
  sidebar: {
    root: {
      base: 'h-full',
      inner: 'h-full overflow-y-auto overflow-x-hidden bg-white px-3 py-4 dark:bg-[#17171C]',
    },
    item: {
      base: 'flex items-center justify-center rounded-xl p-2.5 text-body font-medium text-[#8B95A1] hover:bg-[#F2F4F6] dark:text-gray-500 dark:hover:bg-[#1E1E24]',
      active: 'bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/10 dark:text-[#3182F6]',
      icon: {
        base: 'h-5 w-5 flex-shrink-0 transition duration-75',
        active: 'text-[#3182F6] dark:text-[#3182F6]',
      },
    },
  },
  navbar: {
    root: {
      base: 'bg-white px-4 py-2.5 dark:bg-[#17171C]',
    },
  },
  table: {
    root: {
      base: 'w-full text-left text-body text-[#4E5968] dark:text-gray-400',
      shadow: '',
      wrapper: 'overflow-x-auto',
    },
    head: {
      base: 'group/head text-caption uppercase text-[#8B95A1] dark:text-gray-500',
      cell: {
        base: 'bg-[#F8F9FA] px-5 py-3 font-medium whitespace-nowrap dark:bg-[#1E1E24]',
      },
    },
    body: {
      cell: {
        base: 'px-5 py-3.5 text-body whitespace-nowrap',
      },
    },
    row: {
      base: 'group/row',
      hovered: 'hover:bg-[#F2F4F6] dark:hover:bg-[#1E1E24]',
      striped:
        'odd:bg-transparent even:bg-[#F2F4F6]/40 dark:odd:bg-transparent dark:even:bg-[#1E1E24]/30',
    },
  },
  modal: {
    root: {
      base: 'fixed inset-x-0 top-0 z-50 h-screen overflow-y-auto overflow-x-hidden md:inset-0 md:h-full',
      show: {
        on: 'flex bg-gray-900/50 dark:bg-gray-900/80',
        off: 'hidden',
      },
      sizes: {
        sm: 'max-w-sm',
        md: 'max-w-md',
        lg: 'max-w-lg',
        xl: 'max-w-xl',
        '2xl': 'max-w-2xl',
        '3xl': 'max-w-3xl',
        '4xl': 'max-w-4xl',
        '5xl': 'max-w-5xl',
      },
    },
    content: {
      base: 'relative mx-auto h-full w-full p-4 md:h-auto',
      inner:
        'relative flex max-h-[90dvh] flex-col rounded-2xl bg-white shadow-2xl dark:bg-[#1E1E24]',
    },
  },
  badge: {
    root: {
      base: 'flex h-fit items-center gap-1 rounded-lg px-2 py-0.5 font-medium',
      color: {
        info: 'bg-[#E8F3FF] text-[#3182F6] dark:bg-[#3182F6]/15 dark:text-[#3182F6]',
        success:
          'bg-[#E8FAF5] text-[#00C9A7] dark:bg-[#00C9A7]/15 dark:text-[#00C9A7]',
        warning:
          'bg-[#FFF5E6] text-[#FF9F00] dark:bg-[#FF9F00]/15 dark:text-[#FF9F00]',
        failure:
          'bg-[#FFEBEE] text-[#F04452] dark:bg-[#F04452]/15 dark:text-[#F04452]',
        gray: 'bg-[#F2F4F6] text-[#8B95A1] dark:bg-[#2C2C34] dark:text-gray-400',
      },
    },
  },
  button: {
    base: 'group relative flex items-center justify-center text-center font-medium focus:z-10 focus:outline-none transition-colors',
    color: {
      blue: 'bg-[#3182F6] text-white hover:bg-[#1B64DA] focus:ring-[#3182F6]/30',
      light:
        'bg-[#F2F4F6] text-[#191F28] hover:bg-[#E5E8EB] dark:bg-[#2C2C34] dark:text-gray-200 dark:hover:bg-[#35353E]',
    },
    size: {
      xs: 'px-2 py-1 text-caption',
      sm: 'px-3 py-1.5 text-body',
      md: 'px-4 py-2 text-body',
      lg: 'px-5 py-2.5 text-body',
    },
  },
  tabs: {
    tablist: {
      tabitem: {
        base: 'flex items-center justify-center rounded-t-lg p-4 text-body font-medium',
        variant: {
          underline: {
            base: '-mb-px border-b-2 border-transparent p-4',
            active: {
              on: 'border-[#3182F6] text-[#3182F6] dark:border-[#3182F6] dark:text-[#3182F6]',
              off: 'border-transparent text-[#8B95A1] hover:border-[#B0B8C1] hover:text-[#4E5968] dark:text-gray-500',
            },
          },
        },
      },
    },
  },
  textInput: {
    field: {
      input: {
        sizes: {
          sm: 'p-2 text-body',
          md: 'p-2.5 text-body',
        },
        withIcon: {
          on: 'pl-10',
          off: '',
        },
        withRightIcon: {
          on: 'pr-10',
          off: '',
        },
      },
      rightIcon: {
        base: 'pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3',
      },
    },
  },
  tooltip: {
    target: '',
    animation: 'transition-opacity duration-150',
    arrow: {
      base: 'absolute z-10 h-2 w-2 rotate-45',
      style: {
        dark: 'bg-[#191F28] dark:bg-[#2C2C34]',
        light: 'bg-white dark:bg-[#2C2C34]',
        auto: 'bg-[#191F28] dark:bg-[#2C2C34]',
      },
      placement: '-4px',
    },
    style: {
      dark: 'bg-[#191F28] text-white dark:bg-[#2C2C34] dark:text-gray-100',
      light: 'bg-white text-[#191F28] border border-[#E5E8EB] dark:bg-[#2C2C34] dark:text-gray-100 dark:border-gray-700',
      auto: 'bg-[#191F28] text-white dark:bg-[#2C2C34] dark:text-gray-100',
    },
    content: 'relative z-[60] rounded-lg px-3 py-1.5 text-caption font-medium shadow-lg whitespace-nowrap',
  },
  spinner: {
    color: {
      info: 'fill-[#3182F6]',
    },
  },
  toggleSwitch: {
    root: {
      base: 'group flex rounded-lg focus:outline-none',
      active: {
        on: 'cursor-pointer',
        off: 'cursor-not-allowed opacity-50',
      },
      label: 'ms-3 mt-0.5 text-start text-body font-medium text-[#191F28] dark:text-gray-300',
    },
    toggle: {
      base: 'relative rounded-full border after:absolute after:rounded-full after:bg-white after:transition-all',
      checked: {
        on: 'bg-[#3182F6] border-[#3182F6] after:translate-x-full',
        off: 'bg-gray-200 border-gray-200 dark:bg-gray-600 dark:border-gray-600',
        color: {
          blue: 'bg-[#3182F6] border-[#3182F6]',
        },
      },
      sizes: {
        sm: 'h-5 w-9 min-w-9 after:left-px after:top-px after:h-4 after:w-4',
        md: 'h-6 w-11 min-w-11 after:left-px after:top-px after:h-5 after:w-5',
        lg: 'h-7 w-14 min-w-14 after:left-1 after:top-0.5 after:h-6 after:w-6',
      },
    },
  },
}

export default function FlowbiteWrapper({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <FlowbiteThemeProvider theme={customTheme}>
      {children}
    </FlowbiteThemeProvider>
  )
}
