import sys
from core_logic.agent import Clara_Agent

def main():
    
    print("CLARA System startup")
    
    agent= Clara_Agent(model_name="phi3:mini")
    # user_query= str(input("Enter your query for Clara: "))
    # user_query = "when did USA got it's independence?"
    final_answer=agent.run()
    print(f"Final Answer: {final_answer}\n")
    print("\n Task completed Sir.")

if __name__ == "__main__":
    main()


