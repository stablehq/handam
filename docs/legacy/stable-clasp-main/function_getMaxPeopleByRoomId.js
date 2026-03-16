function getMaxPeopleByRoomId(bizItemId) {
  switch (String(bizItemId)) {
    // 도미
    case "4779029":
    case "4779028":
      return 1;

    // 스위트
    case "4779035":
      return 4;

    // 별관 더블룸
    case "4891205":
      return 2;

    // 별관 트리플룸
    case "4893072":
      return 2;
    
    // 별관 독채
    case "4856805":
      return 2;

    // 별관 디럭스룸 
    case "4887643":
      return 2;

    // 더블, 더블 스파, 트윈 스파, 트윈
    default:
      return 2;
  }
}