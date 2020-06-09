#!/bin/sh
brew_installed=1
if ! which brew >& /dev/null;then
  brew_installed=0
  echo Homebrew is not installed!
  echo Install now...
  echo /bin/bash -c \"\$\(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh\)\"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"
  echo
fi

echo
echo Install Brew-file...
brew install rcmdnk/file/brew-file

if [ $brew_installed -eq 0 ];then
  brew doctor
  if [ $? -ne 0 ];then
    echo Check brew environment!
    exit 1
  fi
fi
